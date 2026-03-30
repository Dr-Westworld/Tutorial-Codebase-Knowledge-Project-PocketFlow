"""
GPU-Accelerated Knowledge Graph Pipeline
==================================================================
GPU: cuDF, cuGraph, Model inference
Features: Hub nodes, dense connectivity, type-aware WSD

INSTALLATION:
!pip install cudf-cu12 cugraph-cu12 --extra-index-url=https://pypi.nvidia.com
!pip install transformers torch accelerate polars pyvis xxhash tqdm numba

import os
os.makedirs("./offload", exist_ok=True)
os.makedirs("./checkpoints", exist_ok=True)
"""

import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
import cudf
import cugraph
import polars as pl
from pyvis.network import Network
import re
from pathlib import Path
from typing import List, Dict, Tuple, Iterator, Optional, Set
import gc
from dataclasses import dataclass
import xxhash
import time
from tqdm.auto import tqdm
import numpy as np
from numba import cuda
import math
import warnings
from collections import Counter
warnings.filterwarnings('ignore')

# Optional RMM imports
RMM_AVAILABLE = False
try:
    import rmm
    from rmm.allocators.torch import rmm_torch_allocator
    import cupy as cp
    RMM_AVAILABLE = True
except ImportError:
    import cupy as cp
    print("⚠️  RMM not available, using default allocators")

print("="*60)
print("GPU KNOWLEDGE GRAPH PIPELINE - INTERCONNECTED")
print("="*60)
print(f"✓ PyTorch CUDA: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"✓ GPU: {torch.cuda.get_device_name(0)}")
print("="*60 + "\n")


@dataclass
class PipelineConfig:
    """Memory-aware configuration for T4 GPU"""
    # LLM constraints
    model_name: str = "Qwen/Qwen2.5-3B-Instruct"
    max_input_tokens: int = 1200
    max_output_tokens: int = 256
    batch_size: int = 4

    # Graph constraints
    edge_vis_limit: int = 20_000
    edge_batch_limit: int = 5_000

    # Visualization
    top_k_nodes: int = 100
    pyvis_height: str = "800px"
    pyvis_width: str = "100%"

    # Debug mode
    debug: bool = True

config = PipelineConfig()


def cleanup_memory():
    """Aggressive memory cleanup"""
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        # torch.cuda.synchronize()

def initialize_rmm_pool() -> bool:
    """Initialize unified CUDA memory pool"""
    if not torch.cuda.is_available() or not RMM_AVAILABLE:
        return False

    try:
        gpu_props = torch.cuda.get_device_properties(0)
        total_memory = gpu_props.total_memory
        pool_size = int(total_memory * 0.75)
        max_size = int(total_memory * 0.85)

        print(f"🔧 Initializing RMM pool: {pool_size/1e9:.1f}GB / {total_memory/1e9:.1f}GB")

        rmm.reinitialize(
            pool_allocator=True,
            initial_pool_size=pool_size,
            maximum_pool_size=max_size
        )

        torch.cuda.memory.change_current_allocator(rmm_torch_allocator)
        print("✓ RMM unified memory pool active")
        return True

    except Exception as e:
        print(f"⚠️  RMM failed: {e}")
        return False

def full_reset():
    """Complete memory reset between runs"""
    cleanup_memory()
    if hasattr(TripleExtractor, '_instance'):
        TripleExtractor._instance = None
        TripleExtractor._model = None
        TripleExtractor._tokenizer = None
    print("✓ Memory reset complete")

# regionTOON GRAMMAR PARSER

def parse_toon_block(text: str) -> List[Tuple[str, str, str, str, str, float]]:
    """
    Parse TOON-formatted text with entity types.
    Returns: List of (source, source_type, predicate, target, target_type, confidence)
    """
    # Pattern with optional types
    pattern = r'TRIPLE\s+source:\s*["\']?([^"\']+?)["\']?(?:\s+type:\s*["\']?([^"\']+?)["\']?)?\s+predicate:\s*["\']?([^"\']+?)["\']?\s+target:\s*["\']?([^"\']+?)["\']?(?:\s+type:\s*["\']?([^"\']+?)["\']?)?\s+confidence:\s*([\d.]+)'

    triples = []
    for match in re.finditer(pattern, text, re.MULTILINE):
        try:
            source = match.group(1).strip()
            source_type = match.group(2).strip() if match.group(2) else "ENTITY"
            predicate = match.group(3).strip()
            target = match.group(4).strip()
            target_type = match.group(5).strip() if match.group(5) else "ENTITY"
            confidence = float(match.group(6))

            if not source or not predicate or not target:
                continue

            confidence = max(0.0, min(1.0, confidence))
            triples.append((source, source_type, predicate, target, target_type, confidence))

        except (ValueError, IndexError):
            continue

    # Fallback: simpler pattern without types
    if not triples:
        simple_pattern = r'TRIPLE\s+source:\s*["\']?([^"\']+?)["\']?\s+predicate:\s*["\']?([^"\']+?)["\']?\s+target:\s*["\']?([^"\']+?)["\']?'
        for match in re.finditer(simple_pattern, text, re.MULTILINE):
            try:
                source = match.group(1).strip()
                predicate = match.group(2).strip()
                target = match.group(3).strip()

                if source and predicate and target:
                    triples.append((source, "ENTITY", predicate, target, "ENTITY", 0.8))
            except:
                continue

    return triples

#endregion

#region TEXT CHUNKING

class TextChunker:
    """Token-aware chunking with safe boundaries"""

    def __init__(self, tokenizer, max_tokens: int = 1200):
        self.tokenizer = tokenizer
        self.max_tokens = max_tokens

    def chunk_text(self, text: str) -> List[str]:
        """Split text into LLM-safe chunks"""
        sentences = re.split(r'(?<=[.!?])\s+', text)
        chunks = []
        current_chunk = []
        current_length = 0

        for sent in sentences:
            try:
                sent_tokens = len(self.tokenizer.encode(sent, add_special_tokens=False))
            except:
                sent_tokens = len(sent.split()) * 1.3

            if current_length + sent_tokens > self.max_tokens:
                if current_chunk:
                    chunks.append(' '.join(current_chunk))
                current_chunk = [sent]
                current_length = sent_tokens
            else:
                current_chunk.append(sent)
                current_length += sent_tokens

        if current_chunk:
            chunks.append(' '.join(current_chunk))

        return chunks if chunks else [text]

#endregion



#region GPU TRIPLE EXTRACTION WITH INTERCONNECTION

class TripleExtractor:
    """GPU-based triple extraction with dense connectivity"""

    _instance = None
    _model = None
    _tokenizer = None

    def __new__(cls, config: PipelineConfig):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config: PipelineConfig):
        if self._model is not None:
            self.config = config
            self.model = self._model
            self.tokenizer = self._tokenizer
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            return

        self.config = config
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        print(f"🔧 Loading model: {config.model_name}")

        self.tokenizer = AutoTokenizer.from_pretrained(
            config.model_name,
            trust_remote_code=True
        )

        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

        self.model = AutoModelForCausalLM.from_pretrained(
            config.model_name,
            torch_dtype=torch.float16,
            device_map="auto",
            trust_remote_code=True,
            low_cpu_mem_usage=True,
            offload_folder="./offload",
            attn_implementation="flash_attention_2"
        )
        self.model.eval()

        for name, param in self.model.named_parameters():
          if not param.is_cuda:
              print(f"⚠️  Layer offloaded to CPU/disk: {name} — consider 4-bit quant")
              break
          else:
              print("✓ All model layers resident in VRAM — no disk offload")

        self._model = self.model
        self._tokenizer = self.tokenizer

        print(f"✓ Model loaded on {self.device}")

        # INTERCONNECTED EXTRACTION PROMPT
        self.system_prompt = """Extract ALL relationships to create an INTERCONNECTED knowledge graph.

CRITICAL: For each entity mentioned, extract MULTIPLE relationships:
- What created/developed/invented it?
- What does it use/contain/enable?
- What is it part of? What type is it?
- Who works with it? Where is it used?

OUTPUT FORMAT:
TRIPLE source:"entity" type:"TYPE" predicate:"relation" target:"entity" type:"TYPE" confidence:0.XX

TYPES: PERSON, ORGANIZATION, TECHNOLOGY, CONCEPT, PRODUCT, LOCATION, EVENT

INTERCONNECTION EXAMPLES:
Text: "Geoffrey Hinton pioneered deep learning at University of Toronto"

Extract ALL these:
TRIPLE source:"Geoffrey Hinton" type:"PERSON" predicate:"pioneered" target:"deep learning" type:"CONCEPT" confidence:0.95
TRIPLE source:"Geoffrey Hinton" type:"PERSON" predicate:"works_at" target:"University of Toronto" type:"ORGANIZATION" confidence:0.95
TRIPLE source:"deep learning" type:"CONCEPT" predicate:"researched_at" target:"University of Toronto" type:"ORGANIZATION" confidence:0.90

Text: "BERT uses transformer architecture developed by Google"

Extract ALL these:
TRIPLE source:"BERT" type:"TECHNOLOGY" predicate:"uses" target:"transformer architecture" type:"CONCEPT" confidence:0.98
TRIPLE source:"BERT" type:"TECHNOLOGY" predicate:"developed_by" target:"Google" type:"ORGANIZATION" confidence:0.99
TRIPLE source:"transformer architecture" type:"CONCEPT" predicate:"developed_by" target:"Google" type:"ORGANIZATION" confidence:0.90
TRIPLE source:"BERT" type:"TECHNOLOGY" predicate:"is_a" target:"language model" type:"CONCEPT" confidence:0.95

RULES:
1. Extract 3-5 triples per sentence (not just 1!)
2. Connect entities mentioned together in same context
3. Add hierarchical links (is_a, part_of, type_of)
4. Cross-reference entities across sentences
5. Create hub nodes (entities with many connections)

Extract from:"""

    def _enhance_connectivity(self, chunk: str, base_triples: List[Tuple[str, str, str, str, str, float]]) -> List[Tuple[str, str, str, str, str, float]]:
        """Add co-occurrence connections between entities"""
        if len(base_triples) < 2:
            return base_triples

        enhanced = list(base_triples)

        # Extract all entities
        entities = {}
        for src, src_type, pred, tgt, tgt_type, conf in base_triples:
            entities[src] = src_type
            entities[tgt] = tgt_type

        chunk_lower = chunk.lower()

        present = {e for e in entities if e.lower() in chunk_lower}

        existing_edges = frozenset(
            frozenset((src, tgt)) for src, _, _, tgt, _, _ in base_triples
        )

        entity_list = list(present)
        for i in range(len(entity_list)):
            for j in range(i + 1, len(entity_list)):
                ent1, ent2 = entity_list[i], entity_list[j]
                if frozenset((ent1, ent2)) not in existing_edges:
                    enhanced.append((
                        ent1, entities[ent1],
                        "related_to",
                        ent2, entities[ent2],
                        0.65
                    ))

        return enhanced

    def extract_with_context(
        self,
        chunk: str,
        previous_entities: Optional[Set[str]] = None,
    ) -> List[Tuple[str, str, str, str, str, float]]:
        """Two-pass extraction with connectivity enhancement"""

        triples = []

        # Pass 1: Local extraction
        local_prompt = f"{self.system_prompt}\n\n{chunk}\n\nTriples:"

        if self.config.debug:
            print(f"\n{'─'*60}")
            print(f"EXTRACTION | Chunk: {len(chunk)} chars")

        try:
            inputs = self.tokenizer(
                local_prompt,
                return_tensors="pt",
                truncation=True,
                max_length=self.config.max_input_tokens
            ).to(self.device)

            if self.config.debug:
                print(f"Input tokens: {inputs['input_ids'].shape[1]}")

            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=self.config.max_output_tokens,
                    do_sample=True,
                    temperature=0.3,
                    top_p=0.9,
                    pad_token_id=self.tokenizer.pad_token_id,
                    eos_token_id=self.tokenizer.eos_token_id
                )

            decoded = self.tokenizer.batch_decode(outputs, skip_special_tokens=True)

            if self.config.debug:
                print(f"Generated: {len(decoded[0])} chars")

            parsed = []
            for text in decoded:
                parsed.extend(parse_toon_block(text))

            if self.config.debug:
                print(f"Extracted: {len(parsed)} triples")

            triples.extend(parsed)

            # ENHANCE: Add co-occurrence connections
            triples = self._enhance_connectivity(chunk, triples)

            if self.config.debug and len(triples) > len(parsed):
                print(f"Enhanced: +{len(triples) - len(parsed)} co-occurrence links")

            del inputs, outputs
            torch.cuda.empty_cache()

        except Exception as e:
            print(f"❌ Extraction error: {e}")
            return []

        # Pass 2: Contextual linking
        if previous_entities and len(previous_entities) > 5:
            entity_list = [e for e in list(previous_entities) if len(e) < 64][:12]

            context_prompt = f"""Known entities: {', '.join(entity_list)}

Text: {chunk}

Extract additional relationships between known entities and new concepts.
Output TOON triples:"""

            try:
                inputs = self.tokenizer(
                    context_prompt,
                    return_tensors="pt",
                    truncation=True,
                    max_length=self.config.max_input_tokens
                ).to(self.device)

                with torch.no_grad():
                    outputs = self.model.generate(
                        **inputs,
                        max_new_tokens=self.config.max_output_tokens,
                        do_sample=True,
                        temperature=0.3,
                        pad_token_id=self.tokenizer.pad_token_id
                    )

                decoded = self.tokenizer.batch_decode(outputs, skip_special_tokens=True)
                for text in decoded:
                    context_triples = parse_toon_block(text)
                    triples.extend(context_triples)

                del inputs, outputs
                torch.cuda.empty_cache()

            except Exception as e:
                if self.config.debug:
                    print(f"⚠️  Context pass: {e}")

        return triples

    def extract_batch(          
        self,
        chunks: List[str],
        previous_entities: Optional[Set[str]] = None,
    ) -> List[List[Tuple[str, str, str, str, str, float]]]:
        prompts = [f"{self.system_prompt}\n\n{chunk}\n\nTriples:" for chunk in chunks]
        
        inputs = self.tokenizer(
            prompts,
            return_tensors="pt",
            truncation=True,
            max_length=self.config.max_input_tokens,
            padding=True,
        ).to(self.device)
        
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=self.config.max_output_tokens,
                do_sample=True,
                temperature=0.3,
                top_p=0.9,
                pad_token_id=self.tokenizer.pad_token_id,
                eos_token_id=self.tokenizer.eos_token_id,
            )
        
        decoded = self.tokenizer.batch_decode(outputs, skip_special_tokens=True)
        
        results = []
        for i, text in enumerate(decoded):
            parsed = parse_toon_block(text)
            enhanced = self._enhance_connectivity(chunks[i], parsed)
            results.append(enhanced)
        
        del inputs, outputs
        torch.cuda.empty_cache()
        
        return results

#endregion


#region GPU TRIPLE STORAGE WITH WSD

class GPUTripleStore:
    """cuDF-based triple storage with type-aware disambiguation"""

    def __init__(self):
        self.triples_df = None
        self._pending_dfs = []

    @staticmethod
    @cuda.jit
    def _hash_kernel(input_strings, string_lengths, output_hashes, n):
        """CUDA kernel for FNV-1a hashing"""
        idx = cuda.grid(1)

        if idx < n:
            FNV_PRIME = 16777619
            FNV_OFFSET = 2166136261

            hash_val = FNV_OFFSET
            start = 0
            for i in range(idx):
                start += string_lengths[i]

            length = string_lengths[idx]

            for i in range(length):
                if start + i < len(input_strings):
                    hash_val = ((hash_val ^ input_strings[start + i]) * FNV_PRIME) & 0xFFFFFFFF

            output_hashes[idx] = hash_val & 0x7FFFFFFFFFFFFFFF

    @staticmethod
    def hash_entity(entity: str, entity_type: str = "ENTITY") -> int:
        """Type-aware entity hashing for WSD"""
        combined = f"{entity}::{entity_type}"
        return xxhash.xxh64(combined.encode('utf-8')).intdigest() & 0x7FFFFFFFFFFFFFFF

    @staticmethod
    def hash_entities_batch_gpu(entities: List[str], entity_types: List[str] = None) -> cp.ndarray:
        """Batch GPU hashing"""
        if len(entities) < 10:
            if entity_types:
                return cp.array([GPUTripleStore.hash_entity(e, t)
                               for e, t in zip(entities, entity_types)], dtype=cp.int64)
            else:
                return cp.array([xxhash.xxh64(e.encode('utf-8')).intdigest() & 0x7FFFFFFFFFFFFFFF
                               for e in entities], dtype=cp.int64)

        try:
            if entity_types:
                combined = [f"{e}::{t}" for e, t in zip(entities, entity_types)]
            else:
                combined = entities

            encoded_list = [e.encode('utf-8') for e in combined]
            flat_bytes = b''.join(encoded_list)
            string_lengths = np.array([len(e) for e in encoded_list], dtype=np.int32)

            input_bytes = np.frombuffer(flat_bytes, dtype=np.uint8)
            output_hashes = np.zeros(len(entities), dtype=np.int64)

            d_input = cuda.to_device(input_bytes)
            d_lengths = cuda.to_device(string_lengths)
            d_output = cuda.to_device(output_hashes)

            threads_per_block = 256
            blocks = math.ceil(len(entities) / threads_per_block)

            GPUTripleStore._hash_kernel[blocks, threads_per_block](
                d_input, d_lengths, d_output, len(entities)
            )

            d_output.copy_to_host(output_hashes)
            return cp.array(output_hashes, dtype=cp.int64)

        except Exception as e:
            if entity_types:
                return cp.array([GPUTripleStore.hash_entity(e, t)
                               for e, t in zip(entities, entity_types)], dtype=cp.int64)
            else:
                return cp.array([xxhash.xxh64(e.encode('utf-8')).intdigest() & 0x7FFFFFFFFFFFFFFF
                               for e in entities], dtype=cp.int64)

    def add_triples(self, triples: List[Tuple[str, str, str, str, str, float]]):
        """Add typed triples to GPU dataframe"""
        if not triples:
            return

        sources = [t[0] for t in triples]
        source_types = [t[1] for t in triples]
        predicates = [t[2] for t in triples]
        targets = [t[3] for t in triples]
        target_types = [t[4] for t in triples]
        confidences = [t[5] for t in triples]

        src_hashes = self.hash_entities_batch_gpu(sources, source_types)
        rel_hashes = self.hash_entities_batch_gpu(predicates)
        dst_hashes = self.hash_entities_batch_gpu(targets, target_types)

        data = {
            'src_id': cudf.Series(src_hashes),
            'rel_id': cudf.Series(rel_hashes),
            'dst_id': cudf.Series(dst_hashes),
            'confidence': cudf.Series(confidences, dtype='float32'),
            'source_str': sources,
            'source_type': source_types,
            'predicate_str': predicates,
            'target_str': targets,
            'target_type': target_types
        }

        new_df = cudf.DataFrame(data)

        self._pending_dfs.append(new_df)

    def flush(self):
        """Flush pending dataframes"""
        if self._pending_dfs:
            self.triples_df = cudf.concat(self._pending_dfs, ignore_index=True)
            self._pending_dfs = []


    def aggregate(self) -> cudf.DataFrame:
        """GPU groupby aggregation"""
        if self.triples_df is None or len(self.triples_df) == 0:
            return cudf.DataFrame()

        agg_df = self.triples_df.groupby(['src_id', 'rel_id', 'dst_id']).agg({
            'confidence': 'mean',
            'source_str': 'first',
            'source_type': 'first',
            'predicate_str': 'first',
            'target_str': 'first',
            'target_type': 'first'
        }).reset_index()

        count_df = self.triples_df.groupby(['src_id', 'rel_id', 'dst_id']).size().reset_index()
        count_df.columns = ['src_id', 'rel_id', 'dst_id', 'count']

        agg_df = agg_df.merge(count_df, on=['src_id', 'rel_id', 'dst_id'])

        return agg_df

#endregion


#region GPU GRAPH ANALYTICS


class GPUGraphAnalyzer:
    """cuGraph-based analytics"""

    def __init__(self, edges_df: cudf.DataFrame):
        self.edges_df = edges_df
        self.graph = None
        self.build_graph()

    def build_graph(self):
        """Construct cuGraph with optimization flags"""
        self.graph = cugraph.Graph(directed=True)
        self.graph.from_cudf_edgelist(
            self.edges_df,
            source='src_id',
            destination='dst_id',
            edge_attr='confidence',
            store_transposed=True
        )

    def compute_metrics(self) -> Dict[str, cudf.DataFrame]:
        """Run GPU graph algorithms"""
        metrics = {}

        try:
            metrics['pagerank'] = cugraph.pagerank(self.graph)
        except Exception as e:
            print(f"⚠️  PageRank failed: {e}")
            unique_nodes = cudf.concat([self.edges_df['src_id'], self.edges_df['dst_id']]).unique()
            metrics['pagerank'] = cudf.DataFrame({
                'vertex': unique_nodes,
                'pagerank': [0.001] * len(unique_nodes)
            })

        try:
            metrics['in_degree'] = self.graph.in_degree()
            metrics['out_degree'] = self.graph.out_degree()
        except Exception as e:
            print(f"⚠️  Degree computation failed: {e}")

        return metrics

#endregion


#region ENHANCED VISUALIZATION

class PyVisAdapter:
    """PyVis with hub node visualization"""

    def __init__(self, config: PipelineConfig):
        self.config = config

    def create_network(
        self,
        edges_df: cudf.DataFrame,
        metrics: Dict[str, cudf.DataFrame]
    ) -> Network:
        """Build network with hub nodes sized by connections"""

        edges_pl = pl.from_arrow(edges_df.to_arrow())

        if len(edges_pl) > self.config.edge_vis_limit:
            print(f"⚠️  Limiting to {self.config.edge_vis_limit} edges")
            edges_pl = edges_pl.sort('confidence', descending=True).head(self.config.edge_vis_limit)

        # Metrics
        pr_pl = pl.from_arrow(metrics['pagerank'].to_arrow())
        pr_dict = dict(zip(pr_pl['vertex'].to_list(), pr_pl['pagerank'].to_list()))

        in_deg_pl = pl.from_arrow(metrics['in_degree'].to_arrow())
        out_deg_pl = pl.from_arrow(metrics['out_degree'].to_arrow())
        in_deg_dict = dict(zip(in_deg_pl['vertex'].to_list(), in_deg_pl['degree'].to_list()))
        out_deg_dict = dict(zip(out_deg_pl['vertex'].to_list(), out_deg_pl['degree'].to_list()))

        # Initialize PyVis
        net = Network(
            height=self.config.pyvis_height,
            width=self.config.pyvis_width,
            directed=True,
            notebook=True,
            cdn_resources='in_line'
        )

        net.set_options("""
        {
          "physics": {
            "barnesHut": {
              "gravitationalConstant": -30000,
              "centralGravity": 0.3,
              "springLength": 200,
              "springConstant": 0.04,
              "damping": 0.09
            }
          },
          "interaction": {
            "hover": true,
            "navigationButtons": true
          }
        }
        """)

        # Node info
        unique_nodes = set(edges_pl['src_id'].to_list() + edges_pl['dst_id'].to_list())
        node_info = {}

        for row in edges_pl.iter_rows(named=True):
            if row['src_id'] not in node_info:
                node_info[row['src_id']] = {
                    'label': row['source_str'],
                    'type': row['source_type']
                }
            if row['dst_id'] not in node_info:
                node_info[row['dst_id']] = {
                    'label': row['target_str'],
                    'type': row['target_type']
                }

        # Color by type
        type_colors = {
            'PERSON': '#FF6B6B',
            'ORGANIZATION': '#4ECDC4',
            'TECHNOLOGY': '#45B7D1',
            'CONCEPT': '#FFA07A',
            'PRODUCT': '#98D8C8',
            'LOCATION': '#F7DC6F',
            'EVENT': '#BB8FCE',
            'ENTITY': '#BDC3C7'
        }

        # Add nodes - SIZE BY DEGREE (hub nodes are HUGE!)
        for node_id in unique_nodes:
            info = node_info.get(node_id, {'label': str(node_id), 'type': 'ENTITY'})
            pr_score = pr_dict.get(node_id, 0.001)

            # Calculate total connections
            in_deg = in_deg_dict.get(node_id, 0)
            out_deg = out_deg_dict.get(node_id, 0)
            total_degree = in_deg + out_deg

            # SIZE = 15 + (connections × 10) - hub nodes 5-10x bigger!
            size = 15 + (total_degree * 10)

            color = type_colors.get(info['type'], '#BDC3C7')

            tooltip = f"""
            <b>{info['label']}</b><br>
            Type: {info['type']}<br>
            Connections: {total_degree}<br>
            In-degree: {in_deg}<br>
            Out-degree: {out_deg}<br>
            PageRank: {pr_score:.4f}
            """

            net.add_node(
                node_id,
                label=info['label'],
                title=tooltip,
                size=size,
                color=color,
                shape='dot',
                font={'size': 14, 'color': '#333'}
            )

        # Add edges
        for row in edges_pl.iter_rows(named=True):
            net.add_edge(
                row['src_id'],
                row['dst_id'],
                title=f"{row['predicate_str']} (conf: {row['confidence']:.2f})",
                label=row['predicate_str'],
                value=float(row['confidence']) * 10,
                color={'opacity': 0.7}
            )

        print(f"✓ Network: {len(unique_nodes)} nodes, {len(edges_pl)} edges")

        return net

    def save_with_stats(self, net: Network, edges_df: cudf.DataFrame, metrics: Dict, filepath: str):
        """Save with embedded statistics"""

        net.save_graph(filepath)

        with open(filepath, 'r', encoding='utf-8') as f:
            html_content = f.read()

        # Calculate stats
        edges_pl = pl.from_arrow(edges_df.to_arrow())
        unique_nodes = set(edges_pl['src_id'].to_list() + edges_pl['dst_id'].to_list())
        type_counts = Counter(edges_pl['source_type'].to_list() + edges_pl['target_type'].to_list())

        in_deg_pl = pl.from_arrow(metrics['in_degree'].to_arrow())
        out_deg_pl = pl.from_arrow(metrics['out_degree'].to_arrow())

        all_degrees = []
        for node in unique_nodes:
            in_deg = in_deg_pl.filter(pl.col('vertex') == node)['degree'].to_list()
            out_deg = out_deg_pl.filter(pl.col('vertex') == node)['degree'].to_list()
            total = (in_deg[0] if in_deg else 0) + (out_deg[0] if out_deg else 0)
            all_degrees.append(total)

        avg_degree = sum(all_degrees) / len(all_degrees) if all_degrees else 0
        max_degree = max(all_degrees) if all_degrees else 0

        stats_html = f"""
        <div style="position: absolute; top: 10px; right: 10px; background: white;
                    padding: 15px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                    font-family: Arial, sans-serif; z-index: 1000; max-width: 280px;">
            <h3 style="margin-top: 0; color: #2c3e50;">📊 Graph Statistics</h3>
            <p><strong>Nodes:</strong> {len(unique_nodes)}</p>
            <p><strong>Edges:</strong> {len(edges_pl)}</p>
            <p><strong>Avg Confidence:</strong> {edges_pl['confidence'].mean():.3f}</p>
            <hr>
            <h4 style="color: #34495e;">🔗 Connectivity:</h4>
            <p><strong>Avg connections/node:</strong> {avg_degree:.1f}</p>
            <p><strong>Max connections:</strong> {max_degree}</p>
            <p style="font-size: 11px; color: #7f8c8d;">
                💡 Larger nodes = more connections
            </p>
            <hr>
            <h4 style="color: #34495e;">🏷️ Entity Types:</h4>
            <ul style="font-size: 12px; padding-left: 20px; margin: 5px 0;">
        """

        for entity_type, count in type_counts.most_common():
            stats_html += f"<li>{entity_type}: {count}</li>"

        stats_html += """
            </ul>
            <hr>
            <p style="font-size: 11px; color: #666;">
                💡 Drag nodes, zoom, click for details
            </p>
        </div>
        """

        html_content = html_content.replace('<body>', f'<body>{stats_html}')

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_content)

#endregion


#region MAIN PIPELINE

class StreamableKGPipeline:
    """Main orchestrator with hub detection"""

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.extractor = TripleExtractor(config)
        self.chunker = TextChunker(self.extractor.tokenizer, config.max_input_tokens)
        self.triple_store = GPUTripleStore()
        self.seen_entities = set()

    def process_text(self, text: str) -> Iterator[Dict]:
        """Stream processing"""
        chunks = sorted(chunks, key=lambda c: len(self.extractor.tokenizer.encode(c, add_special_tokens=False)))
        total_chunks = len(chunks)

        print(f"\n📄 Processing {total_chunks} chunks...")
        print(f"📊 Estimated triples: {total_chunks * 8}-{total_chunks * 15}")

        gds_storage = GPUDirectStorage()
        pbar = tqdm(total=total_chunks, desc="Extracting", unit="chunk")
        start_time = time.time()

        for batch_start in range(0, total_chunks, self.config.batch_size):
            batch = chunks[batch_start : batch_start + self.config.batch_size]
            
            batch_results = self.extractor.extract_batch(
                batch,
                self.seen_entities if len(self.seen_entities) > 0 else None,
            )
            
            for chunk_triples in batch_results:
                self.triple_store.add_triples(chunk_triples)
                for src, src_type, pred, tgt, tgt_type, conf in chunk_triples:
                    self.seen_entities.add(src)
                    self.seen_entities.add(tgt)
            
            if batch_start > 0 and (batch_start // self.config.batch_size) % 5 == 0:
                self.triple_store.flush()
                if self.triple_store.triples_df is not None:
                    gds_storage.save_checkpoint(
                        self.triple_store.triples_df,
                        f"batch_{batch_start:04d}.parquet"
                    )
            
            if (batch_start // self.config.batch_size) % 3 == 0:
                cleanup_memory()
            
            pbar.update(len(batch))
            yield {
                'progress': min(batch_start + self.config.batch_size, total_chunks) / total_chunks,
                'entities': len(self.seen_entities),
            }

        pbar.close()
        print(f"\n✓ Extraction: {time.time() - start_time:.1f}s")
        print(f"✓ Unique entities: {len(self.seen_entities)}")

        # Show hub nodes
        if self.triple_store.triples_df is not None:
            df_arrow = self.triple_store.triples_df.to_arrow()
            df_pl = pl.from_arrow(df_arrow)

            entity_connections = {}
            for src in df_pl['source_str'].to_list():
                entity_connections[src] = entity_connections.get(src, 0) + 1
            for tgt in df_pl['target_str'].to_list():
                entity_connections[tgt] = entity_connections.get(tgt, 0) + 1

            top_hubs = sorted(entity_connections.items(), key=lambda x: x[1], reverse=True)[:5]
            print(f"\n🌟 Top hub nodes (most connected):")
            for entity, connections in top_hubs:
                print(f"   • {entity}: {connections} connections")

    def finalize_graph(self) -> Tuple[cudf.DataFrame, Dict, Network]:
        """Aggregate and analyze"""
        print("\n🔧 Aggregating triples...")
        self.triple_store.flush()
        edges_df = self.triple_store.aggregate()

        if len(edges_df) == 0:
            raise ValueError("No valid triples extracted")

        print(f"✓ Graph: {len(edges_df)} unique edges")

        print("🔧 Running GPU analytics...")
        analyzer = GPUGraphAnalyzer(edges_df)
        metrics = analyzer.compute_metrics()

        print("🔧 Creating visualization...")
        adapter = PyVisAdapter(self.config)
        network = adapter.create_network(edges_df, metrics)

        return edges_df, metrics, network

#endregion

#region GPU-DIRECT STORAGE

class GPUDirectStorage:
    """Checkpointing"""

    def __init__(self, checkpoint_dir: str = "./checkpoints"):
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(exist_ok=True)
        self.checkpoint_counter = 0

    def save_checkpoint(self, df: cudf.DataFrame, name: str = None) -> Path:
        """Save to Parquet"""
        if name is None:
            name = f"checkpoint_{self.checkpoint_counter:04d}.parquet"
            self.checkpoint_counter += 1

        filepath = self.checkpoint_dir / name
        start = time.time()

        try:
            df.to_parquet(str(filepath), compression='snappy')
            elapsed = time.time() - start
            size_mb = filepath.stat().st_size / 1e6
            print(f" Checkpoint: {size_mb:.1f}MB in {elapsed:.2f}s")
        except Exception as e:
            print(f" Checkpoint failed: {e}")

        return filepath
#endregion


#region EXECUTION


def run_pipeline(input_text: str, output_path: str = "knowledge_graph.html"):
    """Execute pipeline"""
    overall_start = time.time()

    rmm_enabled = initialize_rmm_pool()

    if torch.cuda.is_available():
        gpu_mem = torch.cuda.mem_get_info()
        print(f" GPU: {torch.cuda.get_device_name(0)}")
        print(f" Memory: {gpu_mem[0]/1e9:.1f}GB free / {gpu_mem[1]/1e9:.1f}GB total\n")

    cleanup_memory()

    print("="*60)
    print("KNOWLEDGE GRAPH PIPELINE")
    print("="*60)

    pipeline = StreamableKGPipeline(config)

    for status in pipeline.process_text(input_text):
        pass

    print("\n" + "="*60)
    print("FINALIZING")
    print("="*60)

    finalize_start = time.time()
    edges_df, metrics, network = pipeline.finalize_graph()
    print(f"✓ Finalization: {time.time() - finalize_start:.1f}s")

    # Save with stats
    adapter = PyVisAdapter(config)
    adapter.save_with_stats(network, edges_df, metrics, output_path)
    print(f"\n✓ Saved: {output_path}")

    edges_pl = pl.from_arrow(edges_df.to_arrow())
    edges_pl.write_json("kg_edges.json")
    print(f"✓ Saved: kg_edges.json")

    print(f"\n  Total time: {time.time() - overall_start:.1f}s")

    cleanup_memory()

    return network, edges_df

#endregion

#region  SAMPLE DATA

SAMPLE_TEXT = """
The evolution of artificial intelligence represents one of the most transformative technological
revolutions in human history. The field originated in 1956 at the Dartmouth Conference, where
pioneers like John McCarthy, Marvin Minsky, and Allen Newell laid the conceptual foundations
for machine intelligence. McCarthy coined the term "artificial intelligence" and later developed
Lisp, a programming language that became fundamental to AI research.

Deep learning, the driving force behind modern AI, emerged from decades of neural network research.
Geoffrey Hinton, often called the "godfather of deep learning," pioneered backpropagation algorithms
at the University of Toronto in the 1980s. His work, initially dismissed by the broader AI community,
proved revolutionary. Hinton collaborated with Yann LeCun and Yoshua Bengio, collectively earning
the 2018 Turing Award for their contributions to deep learning. LeCun developed convolutional neural
networks while at Bell Labs, which became essential for computer vision. Bengio's research at the
University of Montreal advanced our understanding of neural language models.

The modern deep learning renaissance began around 2012 with AlexNet, a convolutional neural network
developed by Alex Krizhevsky, Ilya Sutskever, and Geoffrey Hinton. AlexNet won the ImageNet competition
by a massive margin, demonstrating that deep learning could outperform traditional computer vision methods.
This breakthrough catalyzed the AI boom. ImageNet itself, created by Fei-Fei Li at Stanford University,
provided the large-scale labeled dataset necessary for training deep networks.

Natural language processing underwent its own revolution with the introduction of transformer architecture.
Vaswani and colleagues at Google published "Attention Is All You Need" in 2017, introducing transformers
that replaced recurrent neural networks. This architecture became the foundation for modern language models.
Google's BERT, released in 2018, demonstrated transformer effectiveness for language understanding. BERT
uses bidirectional training to understand context from both directions in text.

OpenAI, founded by Sam Altman, Elon Musk, and others in 2015, pushed transformer capabilities further.
The organization released GPT (Generative Pre-trained Transformer), which evolved through multiple versions.
GPT-2, released in 2019, generated remarkably coherent text. GPT-3, launched in 2020, scaled to 175 billion
parameters and demonstrated few-shot learning capabilities. GPT-4, released in 2023, incorporated multimodal
understanding, processing both text and images.

The infrastructure enabling modern AI relies heavily on specialized hardware. NVIDIA emerged as the dominant
GPU manufacturer for deep learning. Jensen Huang, NVIDIA's CEO, recognized GPUs' potential for parallel
computation beyond graphics. NVIDIA's CUDA platform, introduced in 2006, allowed developers to harness GPU
power for general computation. The company's A100 and H100 GPUs became the workhorses of AI training.
Google developed its own custom AI accelerators called TPUs (Tensor Processing Units), optimized specifically
for TensorFlow operations.

Deep learning frameworks democratized AI development. Google's TensorFlow, released in 2015, became widely
adopted for production systems. Meta (formerly Facebook) developed PyTorch, which gained popularity in
research communities for its dynamic computation graphs and intuitive interface. Both frameworks leverage
CUDA for GPU acceleration. Keras, created by François Chollet at Google, provided a high-level API that
simplified neural network development.

Computer vision applications of deep learning transformed multiple industries. Tesla implemented neural
networks for autonomous driving, with Andrej Karpathy leading the AI team until 2022. The company's Full
Self-Driving system processes camera inputs through convolutional networks. Waymo, Google's self-driving
subsidiary, developed different approaches using LiDAR and computer vision. Medical imaging benefited
enormously from deep learning, with systems detecting diseases in X-rays and MRIs with radiologist-level
accuracy.

Reinforcement learning achieved remarkable successes through deep learning integration. DeepMind, acquired
by Google in 2014, developed AlphaGo, which defeated world champion Lee Sedol at Go in 2016. This milestone
demonstrated AI's ability to master complex strategic games. Demis Hassabis, DeepMind's co-founder, led the
development of AlphaFold, which solved the protein folding problem and won the 2020 CASP competition.
AlphaFold's success had profound implications for biology and drug discovery.

Large language models continued advancing rapidly. Anthropic, founded by former OpenAI researchers including
Dario Amodei and Daniela Amodei in 2021, developed Claude, an AI assistant focused on safety and reliability.
The company pioneered Constitutional AI, a technique for training helpful, harmless, and honest AI systems.
Google developed PaLM (Pathways Language Model) and later Gemini, competing directly with GPT-4's capabilities.

The open-source AI community made significant contributions. Meta released LLaMA (Large Language Model Meta AI),
providing researchers with powerful base models. Stability AI developed Stable Diffusion, democratizing image
generation technology. Hugging Face, led by Clément Delangue, created a platform for sharing and deploying AI
models, becoming essential infrastructure for the AI community.

Research institutions continued pushing boundaries. Stanford's HAI (Human-Centered Artificial Intelligence)
institute, led by Fei-Fei Li and John Etchemendy, studies AI's societal implications. MIT's CSAIL (Computer
Science and Artificial Intelligence Laboratory) conducts fundamental research across AI domains. The Allen
Institute for AI, founded by Paul Allen, focuses on commonsense reasoning and robust AI systems.

Ethical AI development gained prominence as systems became more powerful. Timnit Gebru and Margaret Mitchell,
formerly at Google, co-authored influential research on bias in language models before their controversial
departures. Their work highlighted risks of training AI on unfiltered internet data. The AI safety community,
including researchers like Stuart Russell at Berkeley, emphasized the importance of alignment between AI systems
and human values.

Industry applications multiplied across sectors. Microsoft integrated GPT-4 into Bing search and Office products
through partnership with OpenAI. GitHub Copilot, powered by OpenAI Codex, transformed software development by
suggesting code completions. Midjourney and DALL-E revolutionized digital art creation through text-to-image
generation. DeepL provided neural machine translation competing with Google Translate.

The AI chip industry expanded beyond NVIDIA. AMD developed Instinct GPUs for AI workloads. Cerebras built
wafer-scale engines for training massive models. Graphcore designed IPUs (Intelligence Processing Units)
optimized for AI computation. Apple developed Neural Engines integrated into its M-series chips for on-device
AI processing.

Regulatory frameworks began emerging as AI capabilities advanced. The European Union proposed the AI Act,
creating risk-based regulations for AI systems. The US established the National AI Initiative, coordinating
federal AI research. China's government invested heavily in AI development while implementing regulations on
algorithmic recommendations.

Looking forward, AI research continues across multiple frontiers. Multimodal models combining vision, language,
and other modalities show promise. Meta's Make-A-Video and Google's Imagen Video extend generative capabilities
to video. Retrieval-augmented generation, combining language models with knowledge retrieval, improves factual
accuracy. Constitutional AI and reinforcement learning from human feedback aim to create more aligned systems.

The democratization of AI accelerated through cloud platforms. Amazon Web Services provides SageMaker for machine
learning workflows. Google Cloud offers Vertex AI for model development and deployment. Microsoft Azure delivers
Machine Learning services integrated with OpenAI models. These platforms reduced barriers to AI adoption for
businesses of all sizes.
"""

#endregion

if __name__ == "__main__":
    full_reset()
    print("\n" + "="*60)
    print("STARTING KNOWLEDGE GRAPH EXTRACTION")
    print("="*60)
    print(f"Input text: {len(SAMPLE_TEXT)} characters")
    print(f"Estimated chunks: {len(SAMPLE_TEXT) // 800}")
    print("="*60)

    network, edges_df = run_pipeline(SAMPLE_TEXT)

    print("\n" + "="*60)
    print("VISUALIZATION READY")
    print("="*60)
    print("\n Open 'knowledge_graph.html' in your browser")
    print(" Raw data: 'kg_edges.json'")
    print(" Checkpoints: './checkpoints/' folder")
    print("\n Pipeline complete!")

    try:
        from IPython.display import HTML, display
        with open('knowledge_graph.html', 'r', encoding='utf-8') as f:
            html_content = f.read()
        display(HTML(html_content))
    except:
        print("\n Download the HTML file to view the interactive graph")

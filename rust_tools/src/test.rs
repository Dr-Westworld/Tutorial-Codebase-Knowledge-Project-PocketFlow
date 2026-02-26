impl Node for MyProcessNode {
    // ... other methods ...
    
    fn max_retries(&self) -> usize {
        3 // Retry up to 3 times
    }
    
    fn wait_ms(&self) -> u64 {
        100 // Wait 100ms between retries
    }
    
    fn exec_fallback(&mut self, _prep_res: &Self::PrepResult, exc: Box<dyn std::error::Error>) 
        -> Result<Self::ExecResult, Box<dyn std::error::Error>> {
        // Provide a default value on failure
        Ok(-1)
    }
}
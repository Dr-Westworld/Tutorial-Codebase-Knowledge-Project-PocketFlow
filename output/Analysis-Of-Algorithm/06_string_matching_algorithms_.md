# Chapter 6: String Matching Algorithms

Welcome back, algorithm adventurers! In our previous chapter, [Dynamic Programming](05_dynamic_programming_.md), we learned how to solve problems efficiently by breaking them into smaller, overlapping subproblems and remembering their solutions. We tackled problems where we needed to find optimal values.

Now, we're going to explore a very common and practical problem: **finding a specific sequence of characters within a larger body of text.**

### The "Find and Replace" Challenge

Imagine you're reading a very long document on your computer, maybe an e-book or a long essay. You remember a specific word or phrase, say "algorithm", and you want to quickly find every place it appears in the document. What do you do? You probably press `Ctrl+F` (or `Cmd+F` on a Mac) and type in the word. Instantly, your computer highlights all occurrences!

How does your computer do this so fast? It uses **String Matching Algorithms**! These algorithms are the clever brains behind all text search functions, from simple document editors to powerful search engines and even tools used in biology to find DNA sequences.

### What are String Matching Algorithms?

Simply put, **string matching algorithms** are methods to find all occurrences of a smaller string (called the "pattern") inside a larger string (called the "text").

Let's define these terms clearly:

*   **Text (T):** The large document or sequence of characters you are searching through.
    *   Example: ` "ABABDABACDABABCABAB" `
*   **Pattern (P):** The smaller word or phrase you are looking for.
    *   Example: ` "ABAB" `

Our goal is to find where "ABAB" appears within "ABABDABACDABABCABAB".

### The Naive Approach: Trying Every Spot

The simplest way to solve this problem, and a great starting point for understanding string matching, is called the **Naive String Matching Algorithm**. It's "naive" because it's straightforward and doesn't use any super-clever tricks. It just systematically checks every single possible position where the pattern *could* start in the text.

Think of it like manually sliding a transparency (your pattern) across a page (your text) and checking if the letters align perfectly at each stop.

### Internal Implementation Walkthrough (Naive Algorithm)

Let's trace how the Naive Algorithm works with an example:

*   **Text (T):** ` "ABABA" `
*   **Pattern (P):** ` "ABA" `

1.  **Compare at Text Index 0:**
    *   Align `P` with `T` starting at `T[0]`.
    *   `T: A B A B A`
    *   `P: A B A`
    *   Compare `T[0]` with `P[0]` (A vs A) - Match!
    *   Compare `T[1]` with `P[1]` (B vs B) - Match!
    *   Compare `T[2]` with `P[2]` (A vs A) - Match!
    *   All characters in `P` matched! We found an occurrence starting at index 0.

2.  **Compare at Text Index 1:**
    *   Shift `P` one position to the right. Align `P` with `T` starting at `T[1]`.
    *   `T: A B A B A`
    *   `P:   A B A`
    *   Compare `T[1]` with `P[0]` (B vs A) - Mismatch!
    *   No match found at this position.

3.  **Compare at Text Index 2:**
    *   Shift `P` one position to the right. Align `P` with `T` starting at `T[2]`.
    *   `T: A B A B A`
    *   `P:     A B A`
    *   Compare `T[2]` with `P[0]` (A vs A) - Match!
    *   Compare `T[3]` with `P[1]` (B vs B) - Match!
    *   Compare `T[4]` with `P[2]` (A vs A) - Match!
    *   All characters in `P` matched! We found an occurrence starting at index 2.

4.  **Stop:** We've reached a point where the pattern can't fit anymore (if we shifted again, the pattern `ABA` would start at index 3, but `T` only has 5 characters, so `T[3]`, `T[4]` would be available, but we need `T[5]` which doesn't exist).

So, the pattern "ABA" was found at positions 0 and 2 in the text "ABABA".

Here's a simple visualization of this process:

```mermaid
sequenceDiagram
    participant Text as "ABABA"
    participant Pattern as "ABA"
    participant Matcher as Compare Characters

    Note over Text,Pattern: Search for "ABA" in "ABABA"
    Text->>Pattern: Align P at index 0 (ABABA vs ABA)
    Matcher->>Matcher: Compare A==A, B==B, A==A
    Matcher-->>Text: Full Match at index 0!

    Text->>Pattern: Shift P, align at index 1 (ABABA vs  ABA)
    Matcher->>Matcher: Compare B==A
    Matcher-->>Text: Mismatch. Move on.

    Text->>Pattern: Shift P, align at index 2 (ABABA vs   ABA)
    Matcher->>Matcher: Compare A==A, B==B, A==A
    Matcher-->>Text: Full Match at index 2!

    Text->>Text: No more possible shifts for Pattern
    Note over Text,Pattern: Search complete. Found at 0 and 2.
```

### Looking at the Code (`string_matching_algorithm.c`)

Let's see how this "slide and compare" idea translates into actual C code. We'll look at pieces from the `string_matching_algorithm.c` file.

First, the `main` function takes user input for the text and pattern, then calls the `match` function:

```c
// string_matching_algorithm.c (main function)
#include<stdio.h>
#include<string.h>

int main() {
    char st[100], pat[100];
    int status;
    printf("*** Naive String Matching Algorithm ***\n");
    printf("Enter the String:\n");
    fgets(st, sizeof(st), stdin);  // Read text safely
    st[strcspn(st, "\n")] = 0;     // Remove newline

    printf("Enter the pattern to match:\n");
    fgets(pat, sizeof(pat), stdin); // Read pattern safely
    pat[strcspn(pat, "\n")] = 0;   // Remove newline

    status = match(st, pat); // Call the matching function
    if (status == -1)
        printf("\nNo match found");
    else
        printf("Match has been found at position %d.", status + 1);
    return 0;
}
```
**Explanation:** This `main` function simply asks the user for the "text" (`st`) and the "pattern" (`pat`). It uses `fgets` for safer input. Then, it calls our `match` function, which does the actual work, and prints whether a match was found and at which (1-indexed) position.

Now, let's look at the `match` function itself. It has an outer loop that iterates through all possible starting positions in the text:

```c
// string_matching_algorithm.c (part of match function)
int match(char st[], char pat[]) {
    int n = strlen(st); // Length of the text string
    int m = strlen(pat); // Length of the pattern string

    // Loop through all possible starting positions for the pattern in the text
    // The pattern can start from index 0 up to (n - m)
    for (int i = 0; i <= n - m; i++) {
        // ... (more code to compare characters) ...
    }
    return -1; // If the loop finishes, no match was found
}
```
**Explanation:** `n` is the length of the text, and `m` is the length of the pattern. The `for (int i = 0; i <= n - m; i++)` loop is crucial. It controls the "sliding" of the pattern. `i` represents the starting index in the `st` (text) where we try to align `pat` (pattern). The loop runs until `i` reaches `n - m`, because if `i` goes beyond this, the pattern wouldn't fully fit in the remaining text. If this loop finishes without finding a match, the function returns `-1`.

Inside that loop, another loop actually compares characters:

```c
// string_matching_algorithm.c (another part of match function)
int match(char st[], char pat[]) {
    int n = strlen(st);
    int m = strlen(pat);
    for (int i = 0; i <= n - m; i++) {
        int j = 0; // Counter for the pattern characters
        // Compare characters of the pattern with the text at current alignment
        while (j < m && st[i + j] == pat[j]) {
            j++; // Move to the next character in the pattern
        }
        // If the inner loop completed, it means all pattern characters matched
        if (j == m)
            return i; // Return the starting index (0-indexed) where match was found
    }
    return -1;
}
```
**Explanation:**
*   `int j = 0;` initializes a counter for the pattern.
*   The `while (j < m && st[i + j] == pat[j])` loop performs the character-by-character comparison. It checks if `j` is still within the bounds of the pattern (`j < m`) AND if the character in the text at the current alignment (`st[i + j]`) matches the character in the pattern (`pat[j]`). If both are true, `j` increments, moving to the next character.
*   `if (j == m)`: If this condition is true after the `while` loop finishes, it means `j` successfully reached the length of the pattern `m`. This implies *all* characters in the pattern matched the text at the current starting position `i`. In this case, we've found a match, so we return `i` (the 0-indexed starting position).

When you run the `string_matching_algorithm.c` program with our example input:

```
*** Naive String Matching Algorithm ***
Enter the String:
ABABA
Enter the pattern to match:
ABA
Match has been found at position 1.
```
**Important Note on Output:** The code is designed to find and return only the *first* occurrence it finds. Our manual walkthrough found matches at indices 0 and 2. The code returns `0`, which is then printed as `status + 1` (1-indexed position), so `1`. If you wanted all matches, you'd modify the code to store all `i` values where `j == m` is true and continue the outer loop.

### Beyond Naive: Faster Algorithms

While the Naive String Matching Algorithm is easy to understand, it can be slow, especially for very long texts and patterns, or when there are many mismatches. For example, if you search for "AAAAAB" in "AAAAAAAAAB", the naive algorithm will compare many 'A's repeatedly before finding a mismatch.

Computer scientists have developed more advanced string matching algorithms that are much faster for many real-world scenarios:

*   **Knuth-Morris-Pratt (KMP) Algorithm:** This algorithm is very clever. When it finds a mismatch, it uses information about the pattern itself to figure out how far to shift the pattern, avoiding unnecessary comparisons. It never "backs up" in the text, only in the pattern!
*   **Rabin-Karp Algorithm:** This algorithm uses hashing. It computes a hash value for the pattern and for windows (subsections) of the text. If the hash values match, then it performs a character-by-character comparison to confirm a true match. This is often faster for large texts.

These advanced algorithms are built on similar principles but include sophisticated optimizations to reduce the number of comparisons. For a beginner, understanding the Naive algorithm is an excellent foundation.

### Conclusion

String Matching Algorithms are fundamental tools in computer science, enabling us to efficiently search for specific sequences of characters within larger texts. We explored the **Naive String Matching Algorithm**, understanding how it systematically slides a pattern across a text, comparing characters at each possible starting position. This simple "try and check" approach provides a solid understanding of the core problem, even if more advanced algorithms offer greater speed for complex scenarios.

This concludes our journey through various essential algorithms! From sorting and connecting networks to finding paths, solving puzzles, optimizing with dynamic programming, and now matching strings, you've gained a broad understanding of how algorithms empower computers to solve complex problems efficiently.

---

Generated by [AI Codebase Knowledge Builder]
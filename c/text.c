// The script constructs frequency list for text.
// Arguments:
//     - Path to input file with text.
//     - Path to output file to store frequency list.

#include <locale.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

#define BUFFER_SIZE 1024

// How many bits is sufficient to encode a character of the language.
#define BITS_PER_CHARACTER 6

// If word has more characters, than this number, it will be truncated and its
// prefix will be used as a whole word.
#define MAX_WORD_SIZE 50

int w = 0;
struct Occurrences* occurrences;

struct BinaryTree {
    struct BinaryTree* subtrees[2];
    int count;
};

// Word and the number of its occurrences in the text.
struct Occurrences {
    wchar_t word[MAX_WORD_SIZE];
    int count;
};

int comparator(const void *x, const void *y) {
    return ((struct Occurrences*) y)->count - ((struct Occurrences*) x)->count;
}

void process(struct BinaryTree* binary_tree, wchar_t* word, int index,
        int code) {

    if (index > 0 && index % BITS_PER_CHARACTER == 0) {
        word[index / BITS_PER_CHARACTER - 1] = code + L'\x0561';
        word[index / BITS_PER_CHARACTER] = L'\0';
        code = 0;
    }
    if (binary_tree == NULL) {
        return;
    }
    if (binary_tree->count > 0) {
        occurrences[w].count = binary_tree->count;
        wcscpy(occurrences[w].word, word);
        w++;
    }
    for (int bit = 0; bit < 2; bit++) {
        if (binary_tree->subtrees[bit] != NULL) {
            process(binary_tree->subtrees[bit], word, index + 1, (code << 1) + bit);
        }
    }
}

int main(int argc, char** argv) {

    setlocale(LC_ALL, "");

    char* input_file_path = argv[1];
    char* output_file_path = argv[2];

    FILE* input_file = fopen(input_file_path, "r");

    struct BinaryTree *binary_tree = malloc(sizeof(struct BinaryTree));
    *binary_tree = (struct BinaryTree) {{NULL, NULL}, 0};

    struct BinaryTree *current = binary_tree;

    wchar_t buffer[BUFFER_SIZE];
    wchar_t word[MAX_WORD_SIZE];
    int word_index = 0;
    int unique_words = 0;

    printf("Reading...\n");

    while (fgetws(buffer, BUFFER_SIZE, input_file) != NULL) {

        int buffer_index = 0;
        wchar_t character;

        while ((character = buffer[buffer_index])) {

            int code = -1; // Case-insensitive encoding for the character.

            if (L'\x0561' <= character && character <= L'\x0587') {
                code = character - L'\x0561';
            } else if (L'\x0531' <= character && character <= L'\x0556') {
                code = character - L'\x0531';
            }

            // If character is of interest.
            if (code >= 0) {
                if (word_index > MAX_WORD_SIZE) {
                    buffer_index++;
                    continue;
                }
                word[word_index] = character;
                word_index++;

                for (int k = 1 << (BITS_PER_CHARACTER - 1); k >= 1;
                        k = k >> 1) {

                    int bit = code & k ? 1 : 0;
                    if (!current->subtrees[bit]) {
                        current->subtrees[bit] =
                            malloc(sizeof(struct BinaryTree));
                        *current->subtrees[bit] =
                            (struct BinaryTree) {{NULL, NULL}, 0};
                    }
                    current = current->subtrees[bit];
                }
            } else {
                if (word_index > 0) {
                    if (!current->count) {
                        unique_words++;
                    }
                    current->count += 1;
                    word[word_index] = 0;
                }
                word[0] = L'\0';
                current = binary_tree;
                word_index = 0;
            }
            buffer_index++;
        }
    }
    fclose(input_file);

    wchar_t str[MAX_WORD_SIZE];
    occurrences = malloc(unique_words * sizeof(struct Occurrences));

    process(binary_tree, str, 0, 0);

    printf("Sorting...\n");
    qsort((void*) occurrences, unique_words, sizeof(struct Occurrences), comparator);

    FILE* output_file = fopen(output_file_path, "w");

    printf("Writing...\n");
    for (int i = 0; i < unique_words; i++) {
        fwprintf(output_file, L"%ls %d\n", occurrences[i].word, occurrences[i].count);
    }
    fclose(output_file);

    return 0;
}

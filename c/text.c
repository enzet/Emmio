#include <stdio.h>
#include <stdlib.h>
#include <stddef.h>
#include <wchar.h>
#include <locale.h>
#include <string.h>

#define BUFFER_SIZE 1024
#define MAX_WORD_SIZE 50


struct Dictionary {
    struct Dictionary* zero;
    struct Dictionary* one;
    int count;
};

void print(struct Dictionary* dictionary, wchar_t* word, int index, int summ) {

    if (index > 0 && index % 6 == 0) {
        word[index / 6] = summ + L'\x0561';
        word[index / 6 + 1] = L'\0';
        summ = 0;
    }
    if (dictionary == NULL) {
        return;
    }
    if (dictionary->count > 0) {
        printf("%ls %d\n", word, dictionary->count);
    }
    if (dictionary->one != NULL) {
        print(dictionary->one, word, index + 1, (summ << 1) + 1);
    }
    if (dictionary->zero != NULL) {
        print(dictionary->zero, word, index + 1, summ << 1);
    }
}

int main(int argc, char** argv) {

	char* input_file_path = argv[1];
	char* output_file_path = argv[2];

    FILE* file = fopen(input_file_path, "r");
    wchar_t word[MAX_WORD_SIZE];
    int i = 0;

    setlocale(LC_ALL, "");

    struct Dictionary *dictionary = malloc(sizeof(struct Dictionary));
    *dictionary = (struct Dictionary){NULL, NULL, 0};

    struct Dictionary *current = dictionary;

    wchar_t buffer[BUFFER_SIZE];
    while (fgetws(buffer, BUFFER_SIZE, file) != NULL) {
        int j = 0;
        while (1) {
            wchar_t c = buffer[j];
            if (!c) {
                break;
            }
            if (L'\x0561' <= c && c <= L'\x0587') {
                if (i < MAX_WORD_SIZE - 1) {
                    word[i] = c;
                    int n = c - L'\x0561';
                    for (int k = 0x20; k >= 1; k = k >> 1) {
                        int bit = n & k ? 1 : 0;
                        if (bit == 0) {
                            if (current->zero == NULL) {
                                current->zero = malloc(sizeof(struct Dictionary));
                                *current->zero = (struct Dictionary){NULL, NULL, 0};
                            }
                            current = current->zero;
                        } else {
                            if (current->one == NULL) {
                                current->one = malloc(sizeof(struct Dictionary));
                                *current->one = (struct Dictionary){NULL, NULL, 0};
                            }
                            current = current->one;
                        }
                    }
                    i++;
                }
            } else if (L'\x0531' <= c && c <= L'\x0556') {
                if (i < MAX_WORD_SIZE - 1) {
                    word[i] = c + 0x30;
                    i++;
                }
            } else {
                if (i > 0) {
                    current->count += 1;
                    word[i] = 0;
                }
                word[0] = 0;
                current = dictionary;
                i = 0;
            }
            j++;
        }
    }
    fclose(file);

    wchar_t str[1000];
    print(dictionary, str, 0, 0);

    return 0;
}

// Frequency list reader processes a text or a corpus of texts and produces a
// list of unique words with the number of their occurrences.
// Author: Sergey Vartanov <me@enzet.ru>
package main

import (
	"bufio"
	"flag"
	"io"
	"os"
	"sort"
	"strconv"
)

func main() {

	inputFilePath := flag.String("i", "", "input file")
	outputFilePath := flag.String("o", "", "output file")
	// language := flag.String("l", "", "language")
	flag.Parse()

	file, err := os.Open(*inputFilePath)
	if err != nil {
		panic("Cannot open " + *inputFilePath)
	}
	defer file.Close()

	reader := bufio.NewReader(file)
	var word string
	words := make(map[string]int)

	for {
		if c, _, err := reader.ReadRune(); err != nil {
			if err == io.EOF {
				break
			} else {
				panic(err)
			}
		} else {
			if '\u0561' <= c && c <= '\u0587' {
				word += string(c)
			} else if '\u0531' <= c && c <= '\u0556' {
				word += string(c + 0x30)
			} else {
				if len(word) > 0 {
					words[word] += 1
				}
				word = ""
			}
		}
	}
	keys := make([]string, 0, len(words))

	for key := range words {
		keys = append(keys, key)
	}

	sort.SliceStable(keys, func(i, j int) bool {
		return words[keys[i]] > words[keys[j]]
	})

	outputFile, err := os.Create(*outputFilePath)
	if err != nil {
		panic("Cannot open " + *outputFilePath)
	}
	defer outputFile.Close()

	space := []byte(" ")
	newLine := []byte("\n")

	for _, key := range keys {
		outputFile.WriteString(key)
		outputFile.Write(space)
		outputFile.Write([]byte(strconv.Itoa(words[key])))
		outputFile.Write(newLine)
	}
}

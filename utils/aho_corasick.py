import sys
import os

sys.path.append(os.path.abspath('../'))
import ahocorasick

def search_keywords_in_text(keywords:list, text):
    # Create an Aho-Corasick automaton
    A = ahocorasick.Automaton()

    # Add keywords to the automaton
    for index, keyword in enumerate(keywords):
        lowercase_keyword = keyword.lower()
        A.add_word(lowercase_keyword, (index, lowercase_keyword))

    # Finalize the automaton
    A.make_automaton()
    lower_text = text.lower()

    # Search through the entire text, not just split words
    found = False
    for end_index, (idx, keyword) in A.iter(lower_text):
        start_index = end_index - len(keyword) + 1
        print(f"Found keyword: '{keyword}' at position {start_index}:{end_index+1}")
        found = True
        break  # Exit on first match
    
    if not found:
        print("No keywords found.")
    return found

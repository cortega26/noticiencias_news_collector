
def sanitize_title(title_input):
    final_title = title_input
    # Sanitize title: ensure it's a string and not a list representation
    if isinstance(final_title, list):
        final_title = final_title[0] if final_title else "Untitled"
    final_title = str(final_title).replace('"', '\\"')
    
    return f'title: "{final_title}"'

def test():
    print("--- Testing Sanitization ---")
    
    # Case 1: String
    t1 = "Normal Title"
    out1 = sanitize_title(t1)
    print(f"Input: '{t1}' -> Output: {out1}")
    assert out1 == 'title: "Normal Title"'

    # Case 2: List
    t2 = ["List Title"]
    out2 = sanitize_title(t2)
    print(f"Input: {t2} -> Output: {out2}")
    assert out2 == 'title: "List Title"'

    # Case 3: Empty List
    t3 = []
    out3 = sanitize_title(t3)
    print(f"Input: {t3} -> Output: {out3}")
    assert out3 == 'title: "Untitled"'
    
    # Case 4: Quotes
    t4 = 'Title with "quotes"'
    out4 = sanitize_title(t4)
    print(f"Input: '{t4}' -> Output: {out4}")
    assert out4 == 'title: "Title with \\"quotes\\""'

    print("\n✅ Verification Passed!")

if __name__ == "__main__":
    test()

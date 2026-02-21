from app import parse_cv_metadata
import sqlite3
import json

def test():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT id, text FROM cvs WHERE id=21").fetchone()
    text = row['text']
    
    metadata = parse_cv_metadata(text)
    print(f"CV {row['id']} Experience: {metadata['experience']} ans")
    print(metadata)

if __name__ == "__main__":
    test()

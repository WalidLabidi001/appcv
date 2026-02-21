import sqlite3
import json
import os
from app import parse_cv_metadata

def re_parse_all_cvs():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, text, metadata_json FROM cvs")
    rows = cursor.fetchall()
    
    for row in rows:
        cv_id = row['id']
        text = row['text']
        
        # New metadata
        new_metadata = parse_cv_metadata(text)
        
        # Update DB
        cursor.execute(
            "UPDATE cvs SET metadata_json = ? WHERE id = ?",
            (json.dumps(new_metadata), cv_id)
        )
        print(f"Updated CV {cv_id}: {new_metadata.get('name')} - {new_metadata.get('specialty')} ({new_metadata.get('experience')} ans)")
    
    conn.commit()
    conn.close()

if __name__ == "__main__":
    re_parse_all_cvs()

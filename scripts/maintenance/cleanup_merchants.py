#!/usr/bin/env python3
#"""Cleanup merchant database with new stopword filtering."""

import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from app.services.categorization.description_cleaner import clean_description
async def cleanup():
    """Regenerate merchant keys using new stopwords."""
    client = AsyncIOMotorClient("mongodb://mongodb:27017")
    print("=== Database Cleanup with New Merchant Key Filtering ===\n")

    merchant_count = await db.merchant_memory.count_documents({})
    inbox_count = await db.transaction_inbox.count_documents({})

    print(f"Current state:")
    print(f"  merchant_memory: {merchant_count} entries")
    print(f"  transaction_inbox: {inbox_count} entries\n")
    print("Clearing auto_detected merchant_memory entries...")
    result = await db.merchant_memory.delete_many({"learned_from": "auto_detected"})
    print(f"  Deleted {result.deleted_count} auto_detected entries\n")
    print("Regenerating merchant keys in transaction_inbox...")
    updated_count = 0
    samples = []
    async for doc in db.transaction_inbox.find({}):
        old_key = doc.get('cleaned_key', '')
        description = doc.get('description', '')
    new_cleaned = clean_description(description)
    new_key = new_cleaned.split()[0] if new_cleaned else old_key

        if new_key and new_key != old_key:
            await db.transaction_inbox.update_one(
                {"_id": doc["_id"]},
                {"$set": {"cleaned_key": new_key}}
            )
            updated_count += 1
            if len(samples) < 3:
                samples.append(f"{old_key} → {new_key}")

    for sample in samples:
        print(f"  {sample}")
    print(f"  Total updated: {updated_count} entries\n")
    final_merchant_count = await db.merchant_memory.count_documents({})
    print(f"Final state:")
    print(f"  merchant_memory: {final_merchant_count} entries")
    print(f"  transaction_inbox: {inbox_count} entries (regenerated keys)\n")
    print("✅ Cleanup complete! Refresh to see changes.")

    client.close()

if __name__ == "__main__":
    asyncio.run(cleanup())

import asyncio
import sys
from motor.motor_asyncio import AsyncIOMotorClient
#!/usr/bin/env python3
"""Cleanup merchant database with new stopword filtering."""

import asyncio
import sys
 from motor.motor_asyncio import AsyncIOMotorClient
from app.services.categorization.description_cleaner import clean_description
from app.services.categorization.merchant_extractor import extract_merchant_key

async def cleanup():
    """Regenerate merchant keys using new stopwords."""
    client = AsyncIOMotorClient("mongodb://mongodb:27017")
    db = client["fintracker"]
    
    print("=== Database Cleanup with New Merchant Key Filtering ===\n")
    
    # Count existing entries
    merchant_count = await db.merchant_memory.count_documents({})
    inbox_count = await db.transaction_inbox.count_documents({})
    
    print(f"Current state:")
    print(f"  merchant_memory: {merchant_count} entries")
    print(f"  transaction_inbox: {inbox_count} entries\n")
    
    if merchant_count > 0:
        print("Sample merchant_memory entries (before cleanup):")
        async for doc in db.merchant_memory.find({}).limit(3):
            print(f"  - cleaned_key='{doc.get('cleaned_key')}', merchant_name='{doc.get('merchant_name')}'")
        print()
    
    if inbox_count > 0:
        print("Sample transaction_inbox entries (before cleanup):")
        async for doc in db.transaction_inbox.find({}).limit(3):
            print(f"  - cleaned_key='{doc.get('cleaned_key')}', merchant_keyword='{doc.get('merchant_keyword')}'")
        print()
    
    # Option 1: Clear merchant_memory (auto_detected entries only)
    print("Clearing auto_detected merchant_memory entries...")
    result = await db.merchant_memory.delete_many({"learned_from": "auto_detected"})
    print(f"  Deleted {result.deleted_count} auto_detected entries\n")
    
    # Option 2: Regenerate merchant keys in transaction_inbox
    print("Regenerating merchant keys in transaction_inbox...")
    updated_count = 0
    
    async for doc in db.transaction_inbox.find({}):
        old_key = doc.get('cleaned_key', '')
        description = doc.get('description', '')
        
        # Re-clean description with new stopwords
        new_cleaned = clean_description(description)
        
        # Extract first token as new key
        new_key = new_cleaned.split()[0] if new_cleaned else old_key
        
        if new_key and new_key != old_key:
            await db.transaction_inbox.update_one(
                {"_id": doc["_id"]},
                {"$set": {"cleaned_key": new_key}}
            )
            updated_count += 1
            if updated_count <= 3:
                print(f"  {old_key} → {new_key}")
    
    print(f"  Updated {updated_count} entries with new merchant keys\n")
    
    # Show final state
    final_merchant_count = await db.merchant_memory.count_documents({})
    print(f"Final state:")
    print(f"  merchant_memory: {final_merchant_count} entries (removed auto_detected)")
    print(f"  transaction_inbox: {inbox_count} entries (regenerated keys)\n")
    
    print("✅ Cleanup complete! Merchants tab will now show discovered merchants with new merchant keys.")
    print("   You may need to refresh your browser to see the changes.")
    
    client.close()

if __name__ == "__main__":
    asyncio.run(cleanup())

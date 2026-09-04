"""
Create Razorpay Payment Links via API

Payment Links are standalone payment pages that customers can use to pay.
Unlike orders, payment links can be created and shared directly.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
import requests
from requests.auth import HTTPBasicAuth


def create_payment_link(amount_paise: int, description: str, customer_name: str, customer_email: str):
    """
    Create a payment link via Razorpay API
    
    Args:
        amount_paise: Amount in paise (e.g., 100000 for Rs 1000)
        description: Description of the payment
        customer_name: Customer name
        customer_email: Customer email
    
    Returns:
        dict with payment link details including short_url
    """
    url = "https://api.razorpay.com/v1/payment_links"
    
    auth = HTTPBasicAuth(settings.razorpay_key_id, settings.razorpay_key_secret)
    
    payload = {
        "amount": amount_paise,
        "currency": "INR",
        "description": description,
        "customer": {
            "name": customer_name,
            "email": customer_email
        },
        "notify": {
            "sms": False,
            "email": False
        },
        "reminder_enable": False,
        "callback_url": "",
        "callback_method": "get"
    }
    
    headers = {
        "Content-Type": "application/json"
    }
    
    response = requests.post(url, json=payload, auth=auth, headers=headers)
    response.raise_for_status()
    
    return response.json()


def main():
    """Create multiple payment links for testing"""
    
    print("=" * 80)
    print(" Razorpay Payment Link Creator")
    print("=" * 80)
    
    key_id = settings.razorpay_key_id
    key_secret = settings.razorpay_key_secret
    
    if not key_id or not key_secret:
        print("\n[ERROR] Razorpay credentials not configured in .env")
        print("\nAdd these to your .env file:")
        print("   RAZORPAY_KEY_ID=rzp_test_YOUR_KEY")
        print("   RAZORPAY_KEY_SECRET=YOUR_SECRET\n")
        return
    
    print(f"\n[*] Using Key ID: {key_id}")
    print("[*] Creating 5 payment links...\n")
    
    links = []
    
    for i in range(1, 6):
        amount = (i * 1000 + 5000) * 100  # Rs 6000, 7000, 8000, 9000, 10000
        description = f"Test Payment {i}"
        customer_name = f"Test Customer {i}"
        customer_email = f"testuser{i}@example.com"
        
        print(f"[{i}/5] Creating payment link for Rs {amount/100}...")
        
        try:
            result = create_payment_link(
                amount_paise=amount,
                description=description,
                customer_name=customer_name,
                customer_email=customer_email
            )
            
            link_id = result.get("id")
            short_url = result.get("short_url")
            
            links.append({
                "id": link_id,
                "url": short_url,
                "amount": amount,
                "description": description
            })
            
            print(f"   [OK] {short_url}")
            
        except Exception as e:
            print(f"   [ERROR] Failed: {e}")
    
    if not links:
        print("\n[ERROR] No payment links were created")
        return
    
    print(f"\n[SUCCESS] Created {len(links)} payment link(s)!")
    
    # Save links to file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"payment_links_{timestamp}.txt"
    
    with open(filename, "w") as f:
        f.write("Razorpay Payment Links\n")
        f.write("=" * 80 + "\n")
        f.write(f"Created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Total Links: {len(links)}\n\n")
        
        for i, link in enumerate(links, 1):
            f.write(f"{i}. {link['description']} - Rs {link['amount']/100}\n")
            f.write(f"   URL: {link['url']}\n")
            f.write(f"   ID:  {link['id']}\n\n")
    
    print(f"\n[SAVED] Payment links saved to: {filename}")
    
    # Display instructions
    print("\n" + "=" * 80)
    print(" NEXT STEPS")
    print("=" * 80)
    
    print("\n1. Open these payment links in your browser:\n")
    for i, link in enumerate(links, 1):
        print(f"   {i}. {link['url']} (Rs {link['amount']/100})")
    
    print("\n2. Use test card details:")
    print("   Card Number: 4111 1111 1111 1111")
    print("   CVV:         123")
    print("   Expiry:      12/26")
    print("   Name:        Any name")
    
    print("\n3. After completing payments, check captured payments:")
    print("   python scripts/fetch_and_sync_payments.py")
    
    print("\n4. View in dashboard:")
    print("   https://dashboard.razorpay.com/app/payment-links")
    
    print("\n" + "=" * 80)
    print(" TIP: You can also open links directly from the saved file!")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()

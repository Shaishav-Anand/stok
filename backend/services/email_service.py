"""
Email Service — uses Resend API (free tier: 100 emails/day)
No phone verification needed. Works on Render free tier.
"""
import urllib.request
import urllib.error
import json
import os
from datetime import datetime

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
MANAGER_EMAIL = os.getenv("MANAGER_EMAIL", "anandshaishav@gmail.com")
FROM_EMAIL = "onboarding@resend.dev"  # Resend's default sender (works without domain)


def send_email(to: str, subject: str, html_body: str) -> bool:
    """Send email via Resend API. Returns True if successful."""
    if not RESEND_API_KEY:
        print(f"[Email] Skipping — RESEND_API_KEY not set")
        return False

    payload = json.dumps({
        "from": f"STOK Inventory <{FROM_EMAIL}>",
        "to": [to],
        "subject": subject,
        "html": html_body
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            print(f"[Email] Sent '{subject}' to {to} — status {response.status}")
            return True
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"[Email] Resend error {e.code}: {body}")
        return False
    except Exception as e:
        print(f"[Email] Failed: {e}")
        return False


def send_purchase_order_email(action, sku, supplier=None) -> bool:
    supplier_name = supplier.name if supplier else "Not assigned"
    supplier_email = supplier.contact_email if supplier and supplier.contact_email else "N/A"
    qty = action.recommended_qty or 0
    value = action.recommended_value or 0
    unit_cost = round(value / qty, 2) if qty > 0 else 0

    subject = f"[STOK] PO Approved — {sku.name} ({qty} units)"
    html = f"""
    <html><body style="font-family:Arial,sans-serif;background:#f5f5f5;padding:20px;">
    <div style="max-width:600px;margin:0 auto;background:white;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1)">
      <div style="background:#0a0a0f;padding:24px;text-align:center">
        <h1 style="color:#00ff88;margin:0;font-size:24px;letter-spacing:2px">STOK</h1>
        <p style="color:#6b6b88;margin:6px 0 0;font-size:12px">Purchase Order Approved</p>
      </div>
      <div style="padding:28px">
        <div style="background:#f0fff8;border:1px solid #00cc66;border-radius:6px;padding:16px;margin-bottom:20px">
          <p style="margin:0;color:#006633;font-weight:bold">✓ Order Approved & Executed</p>
          <p style="margin:4px 0 0;color:#009944;font-size:12px">{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</p>
        </div>
        <h2 style="font-size:18px;margin:0 0 16px">{sku.name}</h2>
        <table style="width:100%;border-collapse:collapse;font-size:14px">
          <tr style="background:#f8f8f8"><td style="padding:10px;color:#666;border-bottom:1px solid #eee">SKU</td><td style="padding:10px;font-weight:600;border-bottom:1px solid #eee">{sku.sku_code}</td></tr>
          <tr><td style="padding:10px;color:#666;border-bottom:1px solid #eee">Quantity</td><td style="padding:10px;font-weight:600;border-bottom:1px solid #eee">{qty} units</td></tr>
          <tr style="background:#f8f8f8"><td style="padding:10px;color:#666;border-bottom:1px solid #eee">Unit Cost</td><td style="padding:10px;font-weight:600;border-bottom:1px solid #eee">${unit_cost}</td></tr>
          <tr><td style="padding:10px;color:#666;border-bottom:1px solid #eee">Total Value</td><td style="padding:10px;font-weight:700;color:#0a7a3c;border-bottom:1px solid #eee">${value:,.2f}</td></tr>
          <tr style="background:#f8f8f8"><td style="padding:10px;color:#666;border-bottom:1px solid #eee">Supplier</td><td style="padding:10px;font-weight:600;border-bottom:1px solid #eee">{supplier_name}</td></tr>
          <tr><td style="padding:10px;color:#666">Supplier Email</td><td style="padding:10px;font-weight:600">{supplier_email}</td></tr>
        </table>
        <div style="background:#fffbf0;border:1px solid #ffd166;border-radius:6px;padding:14px;margin-top:20px">
          <p style="margin:0;font-size:12px;color:#664d00"><strong>AI Justification:</strong><br>{action.justification}</p>
        </div>
        <div style="margin-top:20px;padding-top:16px;border-top:1px solid #eee;font-size:11px;color:#999;text-align:center">
          Approved via STOK Agentic Inventory Manager
        </div>
      </div>
    </div>
    </body></html>
    """
    return send_email(MANAGER_EMAIL, subject, html)


def send_markdown_email(action, sku) -> bool:
    change_pct = abs(action.recommended_value or 15)
    subject = f"[STOK] Price Markdown Approved — {sku.name} (-{change_pct}%)"
    html = f"""
    <html><body style="font-family:Arial,sans-serif;background:#f5f5f5;padding:20px;">
    <div style="max-width:600px;margin:0 auto;background:white;border-radius:8px;padding:28px">
      <h1 style="color:#00ff88">STOK</h1>
      <h2>{sku.name} — {sku.sku_code}</h2>
      <p><strong>Action:</strong> Markdown -{change_pct}%</p>
      <p><strong>Current Price:</strong> ${sku.unit_price or 'N/A'}</p>
      <p><strong>New Price:</strong> ${round((sku.unit_price or 0) * (1 - change_pct/100), 2)}</p>
      <p style="color:#666;font-size:12px">{action.justification}</p>
    </div>
    </body></html>
    """
    return send_email(MANAGER_EMAIL, subject, html)


def send_agent_summary_email(actions_created: int, skus_scanned: int, urgent_count: int) -> bool:
    if urgent_count == 0:
        return False
    subject = f"[STOK] ⚠️ {urgent_count} Urgent Action{'s' if urgent_count > 1 else ''} Need Review"
    app_url = os.getenv("RENDER_EXTERNAL_URL", "https://stok-inventory.onrender.com")
    html = f"""
    <html><body style="font-family:Arial,sans-serif;background:#f5f5f5;padding:20px;">
    <div style="max-width:600px;margin:0 auto;background:white;border-radius:8px;padding:28px;text-align:center">
      <h1 style="color:#00ff88">STOK</h1>
      <div style="background:#fff0f0;border:1px solid #ff4757;border-radius:6px;padding:20px;margin:20px 0">
        <p style="font-size:36px;font-weight:bold;color:#cc0000;margin:0">{urgent_count}</p>
        <p style="color:#cc0000">urgent action{'s' if urgent_count > 1 else ''} need your review</p>
      </div>
      <p>SKUs scanned: {skus_scanned} | New actions: {actions_created}</p>
      <a href="{app_url}" style="background:#00ff88;color:#0a0a0f;padding:12px 28px;border-radius:6px;text-decoration:none;font-weight:bold">
        Review Now →
      </a>
    </div>
    </body></html>
    """
    return send_email(MANAGER_EMAIL, subject, html)

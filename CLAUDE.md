# Project: SmartShop AI Agent (2026 SOTA Architecture)

## 1. Project Overview
SmartShop is an autonomous AI concierge. Users search for products via a natural language chat; the AI returns the top 3 options (Generative UI), and the user selects one for autonomous checkout. We use a **Bring Your Own Card (BYOC)** model to remain a pure SaaS, avoiding all FinTech/ledger regulations.

## 2. Core Tech Stack
*   **Frontend:** Next.js (App Router, TailwindCSS)
*   **Backend:** FastAPI (Python 3.12+)
*   **Database:** Supabase (PostgreSQL)
*   **AI/LLM:** Gemini (Intent, Scoring, Logic), Tavily (Search/Discovery)
*   **Authentication:** WebAuthn / Passkeys (Biometric)
*   **Billing (MoR):** Lemon Squeezy (Handles global taxes/compliance)

## 3. Strict Architectural Rules
*   **The "No PCI-DSS" Rule:** Card numbers are NEVER stored in the DB. They move from Next.js -> FastAPI RAM -> checkout automation -> Purge. Use HTML5 `autocomplete` to trigger OS-level biometric (Face ID/Touch ID) autofill for the user.
*   **The "Concierge" Rule:** Shipping address, phone, and name ARE stored in Supabase for checkout auto-fill. The user only provides the card at purchase time.
*   **The "Zero Ledger" Rule:** No internal wallets or top-ups. We do not hold user funds. We only charge for the SaaS subscription ($9.99/mo).

## 4. Database Schema (Supabase)
*   **`Users` Table:**
    *   `id` (UUID, PK)
    *   `email` (Unique String)
    *   `full_name`, `phone`, `shipping_address` (PII for Concierge auto-fill)
    *   `tier` ('free' or 'pro')
    *   `monthly_credits` (Integer, defaults to 2 for free users)
    *   `lemon_squeezy_id` (String)
*   **`Passkeys` Table:**
    *   `credential_id`, `public_key`, `user_id` (FK to Users)
*   **`Chat_History` Table:**
    *   `user_id` (FK), `prompt`, `response_json` (Stores the Top 3 products found)

## 5. The State-Machine Flow
1.  **Registration:** User signs up via Passkey and provides shipping details (Stored).
2.  **Search (Free):** User prompts for a product. Gemini uses Tavily/Jina to find 3 options.
3.  **Generative UI:** Next.js renders 3 interactive product cards.
4.  **Selection:**
    *   If **Pro/Credits > 0**: User clicks "Buy" -> Triggers Ephemeral Card Form.
    *   If **Free/Credits == 0**: User sees "Unlock Auto-Checkout" or an Affiliate Link.
5.  **Ephemeral Intake:** User taps card input; OS triggers **Face ID**; form autofills. Card details sent to FastAPI.
6.  **Execution (Checkout Automation):** 
    *   FastAPI fetches address from DB + Card from RAM.
    *   Browser automation navigates, adds to cart, fills address, inputs card, clicks pay.
7.  **Pivot/Teardown:**
    *   If **Sold Out**: AI suggests the 2nd best item (State Pivot).
    *   If **Success/Fail**: FastAPI **violently deletes card from RAM** and reports to UI.


















    
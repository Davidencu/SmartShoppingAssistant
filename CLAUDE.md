# SmartShop Assistant (2026 SOTA)

## 🏗 Architecture & Tech Stack
- **Frontend (UI/UX)**: Next.js 15, TypeScript, Tailwind CSS, Lucide React (Vercel deployment)
- **Backend (Orchestrator)**: Python 3.12+, FastAPI, Pydantic (Railway deployment)
- **Database & Auth**: Supabase PostgreSQL, Supabase WebAuthn (Passkeys)
- **AI Agentic Layer**: Gemini 1.5 Flash (Brain), Stagehand (Execution), Tavily (Search), Jina (Extraction)
- **Fintech Layer**: Lithic API (Virtual Cards), LemonSqueezy (Wallet Top-Ups)

## 🛑 Hard Architectural Rules
1. **Agentic Execution, No Legacy Scraping**: NEVER write bare-metal Playwright, Selenium, or Puppeteer DOM selectors. ALWAYS use `Stagehand` with the `page.act()` natural language syntax for web navigation.
2. **Strict Passkey Authentication**: Do not write traditional email/password flows. All authentication and purchase approvals must route through Supabase WebAuthn (FaceID/TouchID).
3. **Master-Ledger Integrity**: Do not update the Supabase wallet ledger on the backend unless money has physically moved (LemonSqueezy webhook) or is being frozen/refunded (Lithic API). Top-up UI failures belong strictly to the frontend.
4. **The Saga Pattern**: If Stagehand fails a checkout, the system must immediately trigger the fallback state to void the Lithic card and unfreeze the user's funds.

## 💻 Non-Obvious Commands
- **Run Frontend**: `cd frontend && npm run dev`
- **Run Backend**: `cd backend && fastapi dev main.py`
- **Update Database**: `supabase db push` (Run from project root)

## 🧠 Code Style & Conventions
- **Python**: Use strict typing with Pydantic for all FastAPI endpoints.
- **Next.js**: Default to React Server Components unless `use client` is explicitly required for biometric triggers or LemonSqueezy UI components.
- **Error Handling**: Fail gracefully. If an API times out, return a human-readable recovery prompt to the Next.js frontend rather than a raw server crash log.

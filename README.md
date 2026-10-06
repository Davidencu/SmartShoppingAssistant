# SmartShop AI — Your Personal Shopping Assistant

**Tell SmartShop what you want to buy and how much you want to spend. It searches real online shops, reads the product pages, compares prices, quality and delivery, and shows you the three best options, ranked by value rather than by who paid for advertising.**

You talk to it like you would talk to a friend who knows a lot about shopping:

> *"I need a fridge under 2000 RON"*
> *"Sony noise-cancelling headphones, max 1500 lei"*
> *"Find me something cheaper"*

SmartShop asks a follow-up question if something important is missing (for example, your budget), then does all the tedious work for you: searching, opening dozens of pages, checking stock and shipping, and comparing everything side by side.

---

## Table of Contents

1. [What SmartShop Can Do Today](#what-smartshop-can-do-today)
2. [What Happens When You Search](#what-happens-when-you-search)
3. [Technologies Used](#technologies-used)
4. [How Logging In Works](#how-logging-in-works)
5. [How Shops Are Chosen](#how-shops-are-chosen)
6. [How SmartShop Reads Shop Websites](#how-smartshop-reads-shop-websites)
7. [How Products Are Scored](#how-products-are-scored)
8. [How SmartShop Stays Fast](#how-smartshop-stays-fast)
9. [The Two AI Models and How They Work Together](#the-two-ai-models-and-how-they-work-together)
10. [The Website (Frontend)](#the-website-frontend)
11. [Database](#database)
12. [Project Structure](#project-structure)
13. [Running It on Your Computer](#running-it-on-your-computer)
14. [Settings (Environment Variables)](#settings-environment-variables)
15. [Running the Tests](#running-the-tests)
16. [Known Limitations](#known-limitations)
17. [Design Rules](#design-rules)
18. [Glossary](#glossary)

---

## What SmartShop Can Do Today

**Working:**

- **Chat-based search.** Describe what you want in plain language, in English, Romanian, German, French, Italian, Spanish, Polish, Dutch or Portuguese.
- **Follow-up questions.** If you leave out something important (the budget, or what you'll use a laptop for), it asks before searching.
- **Real shop results.** It looks at real product pages from real shops, not made-up listings.
- **Top 3 picks.** You get three product cards with price, a value score, a short explanation, and a link to the shop.
- **Refining.** Say "cheaper", "a different brand" or "not satisfied" and it searches again with that in mind.
- **Local first.** It prefers shops in your country, and only searches worldwide when nothing local fits.
- **Passwordless login.** You sign in with your fingerprint or face (a *passkey*), not a password.
- **Search history.** Your last 50 conversations are saved so you can look back at them.
- **Dark mode.**

**Not built yet:**

- **Buying for you.** The original plan was for the AI to complete the purchase on your behalf. That part doesn't exist. Clicking a product takes you to the shop's own page, where you buy it yourself.
- **Paid plans / subscriptions.** Not built.

---

## What Happens When You Search

Here is the journey of a single message, for example *"fridge under 2000 RON"*. The whole thing usually takes 5–15 seconds. While it runs, the screen shows live updates like *"Searching for products…"* and *"Opening eMAG…"*, so you're never staring at a blank page.

```
 You type a message
        │
        ▼
 ① Understand the request ......... What do you want? Budget? Which kind of shop sells it?
        │
        ├── Just chatting or missing info? → reply / ask a question, stop here
        ▼
 ② Check the memory ............... Has someone asked almost the same thing recently?
        │
        ├── Yes → show those results instantly, stop here
        ▼
 ③ Ask the community .............. What do reviewers and forums recommend?
        │
        ▼
 ④ Find product pages ............. Search the web, only in shops that sell this kind of product
        │
        ▼
 ⑤ Read the pages ................. Open each page, pull out price, stock, rating, delivery
        │
        ▼
 ⑥ Score and rank ................. Compare everything, pick the best 3
        │
        ▼
 ⑦ Double-check ................... Are these really fridges, not fridge magnets?
        │
        ▼
 You see 3 product cards
```

### ① Understanding the request

An AI model reads your whole conversation and works out:

- **What kind of message it is.** Just chatting ("hello"), missing information ("I want a laptop", with no budget), or ready to search.
- **The details.** Product type, budget, currency and preferences ("Samsung", "for gaming", "size 42").
- **Search words in your local language.** Romanian shops are searched with *"frigider"*, not *"fridge"*, because that's what their pages say.
- **Which kind of shop sells it.** A fridge comes from an appliance shop, not a perfume shop. See [How Shops Are Chosen](#how-shops-are-chosen).
- **Specific models worth checking.** For example, real fridge models that fit the budget.
- **Whether you're refining.** "Cheaper" means: re-use the last search, but lower the budget.

For complex purchases (laptops, phones, TVs, fridges, washing machines and so on), it asks one question about *how* you'll use the product before searching. A gaming laptop and an office laptop are very different things.

### ② Checking the memory (cache)

If someone searched for nearly the same thing in the last **6 hours**, SmartShop shows those results straight away. It understands that *"ASUS laptop under 3000 RON"* and *"ASUS laptop max 3000 lei"* mean the same thing, even though the words differ. The memory is skipped when you ask for something cheaper or reject the previous results.

### ③ Asking the community

At the same time as the main search, an AI looks up what reviewers, forums and Reddit recommend for your request. This advice is shown to you while you wait, and it gives a small boost to products the community likes.

### ④ Finding product pages

SmartShop asks a search engine built for AI tools (Tavily) for product pages, but **only on shops that sell your kind of product**. It tries shops in this order and stops as soon as it finds good results:

1. **Specialty shops** in your country, plus specialty shops that ship internationally
2. **Big shops** in your country (eMAG, Altex, Flanco…)
3. **Big shops worldwide** (Amazon, eBay…). You'll see a note if this happens.

Specialty shops come first because their pages are easier to read and they often stock things the big shops don't.

Pages that clearly aren't a single product (category pages, search results, blog posts) are thrown out before anything is downloaded.

### ⑤ Reading the pages

Each product page is downloaded and the useful facts are pulled out: price, whether it's in stock, star rating, number of reviews, brand and delivery information. Out-of-stock and over-budget products are removed here. See [How SmartShop Reads Shop Websites](#how-smartshop-reads-shop-websites).

### ⑥ Scoring and ranking

An AI scores each remaining product on value for money, quality, delivery and seller trust. The final score is then calculated by plain code, not by the AI, so the maths is always correct. See [How Products Are Scored](#how-products-are-scored).

### ⑦ Double-checking

A second, different AI model looks at the top picks and removes anything that isn't the type of product you asked for. This catches mistakes like returning a fridge *filter* when you wanted a fridge.

### If nothing is found

You never get an empty error page. SmartShop either widens the search (local → worldwide) or explains why nothing fit and suggests what to change, for example raising the budget a little.

---

## Technologies Used

### At a glance

| Part | Technology | What it does, in plain words |
|---|---|---|
| **Website** | Next.js 16, React 19, TypeScript | The pages you see and click on in your browser |
| **Look and feel** | Tailwind CSS, Lucide icons, next-themes | Styling, icons and dark mode |
| **Server** | Python, FastAPI, Uvicorn | The "brain" behind the website that runs every search |
| **Database** | Supabase (PostgreSQL + pgvector) | Stores accounts, chat history, the shop list and saved search results |
| **Understanding requests** | OpenAI `gpt-4o-mini` | Reads your message and works out what you want |
| **Scoring and research** | Google Gemini 2.5 Flash | Compares products, reads delivery policies, finds community picks |
| **Search memory** | Gemini Embedding 001 | Turns a search into numbers so similar searches can be recognised |
| **Finding pages** | Tavily | A web search engine designed to be used by AI tools |
| **Reading pages** | curl_cffi, BeautifulSoup, lxml | Downloads shop pages and pulls out prices and other facts |
| **Getting past blocks** | IPRoyal residential proxy (optional) | A backup route for shops that block automated visitors |
| **Login** | Passkeys (WebAuthn), email codes, JWT tokens | Lets you sign in with your fingerprint or face instead of a password |
| **Testing** | pytest (server), Jest + Testing Library (website) | Automatic checks that the code still works |

### Website (frontend)

- **Next.js 16** with the App Router: the framework that builds and serves the pages.
- **React 19** and **TypeScript**: the building blocks of the pages. TypeScript catches certain mistakes before the code runs.
- **Tailwind CSS**: styling, including dark mode.
- **next-themes**: remembers whether you prefer light or dark mode.
- **lucide-react**: icons.
- **@simplewebauthn/browser**: talks to your device's fingerprint or face sensor during login.
- **libphonenumber-js**: checks that a phone number is valid when you register.
- **Jest** and **React Testing Library**: automatic tests for the pages.

### Server (backend)

- **Python** with **FastAPI**: the web server that handles logins and searches.
- **Uvicorn**: runs the FastAPI server.
- **Server-Sent Events**: lets the server send live progress updates to your screen during a search, instead of making you wait for the final answer.
- **Pydantic** and **pydantic-settings**: check that data has the right shape, and read the settings file.
- **python-dotenv**: loads secret keys from the `.env` file.
- **webauthn**: verifies passkey logins on the server side.
- **python-jose**: creates and checks the login token that keeps you signed in for 24 hours.
- **supabase** (Python client): talks to the database.
- **httpx**: makes web requests to outside services.

### AI and search services

- **OpenAI `gpt-4o-mini`**: understands your message, double-checks the final picks, and acts as a backup scorer if Gemini is unavailable.
- **Google Gemini 2.5 Flash**: scores products, researches community recommendations, reads shop delivery policies, and takes over understanding your message if OpenAI is unavailable.
- **Gemini Embedding 001**: turns each search into a list of 768 numbers that captures its meaning, so the search memory can recognise similar searches.
- **Tavily**: finds product pages on the web, limited to the shops SmartShop chooses.

### Reading shop websites

- **curl_cffi**: downloads web pages while looking like a normal Chrome or Edge browser, so fewer shops block it.
- **BeautifulSoup** and **lxml**: read the downloaded page and pull out the price, rating, stock and so on.
- **IPRoyal residential proxy** (optional, paid): sends a request through a normal home internet connection when a shop blocks the direct attempt.
- **Internet Archive**: a last-resort source of saved copies of pages.

### Database

- **Supabase**: a hosted database service built on **PostgreSQL**.
- **pgvector**: a PostgreSQL add-on that lets the database compare searches by meaning (used by the search memory).

---

## How Logging In Works

SmartShop has **no passwords**. Instead, it uses *passkeys*, the same technology as "Sign in with Face ID" on many apps. Your fingerprint or face never leaves your device. The device only proves to the server that it's really you.

### Registering (once)

1. Enter your email, phone number, city and country (state/county is optional).
2. You receive a **6-digit code** by email. Type it in to prove the email is yours.
3. Your device asks for your fingerprint, face or PIN, and creates a passkey.
4. You're in. You stay signed in for **24 hours**.

Your city and country are used to search shops near you and to judge delivery times. No street address is collected.

### Signing in

1. Type your email.
2. Use your fingerprint or face when your device asks.
3. You're in.

<details>
<summary><b>Technical details</b></summary>

- Registration: `POST /auth/send-otp` → `POST /auth/verify-otp` (Supabase creates the account, the backend writes the `profiles` row and generates WebAuthn options) → browser `navigator.credentials.create()` → `POST /auth/passkey/register` (verified with `py-webauthn`, stored in `passkeys`).
- Login: `POST /auth/check-email` → `POST /auth/passkey/challenge` → browser `navigator.credentials.get()` → `POST /auth/passkey/verify`. The signature counter is updated to block replayed logins.
- On success the backend issues a 24-hour HS256 JWT, stored in the browser's `localStorage` as `smartshop_token`. The dashboard sends you back to `/login` if the token is missing or rejected.
- `/auth/verify-magic` is a fallback for email magic links.

</details>

---

## How Shops Are Chosen

SmartShop keeps a list of several hundred online shops in the database (the `supported_retailers` table). Every shop has four labels:

| Label | Meaning | Example |
|---|---|---|
| **Country** | Where the shop sells, or `GLOBAL` for shops that ship worldwide | `RO`, `DE`, `GLOBAL` |
| **Tier** | `niche` = specialty or mid-sized shop. `mainstream` = big marketplace | pcgarage.ro is niche, emag.ro is mainstream |
| **Category** | What the shop sells. A shop can have several | altex.ro = electronics + appliances |
| **Needs proxy** | Whether the shop blocks automated visitors | Amazon = yes |

### Why categories matter

Without categories, a search for a fridge would also be sent to perfume shops and toy shops, because they're "specialty shops in Romania" too. That wasted time and money and returned nonsense like baby teethers. Now, when you ask for a fridge, the AI decides that the right kind of shop is `appliances`, and **only shops tagged with that category are searched**.

A shop is picked when **all** of these are true:

1. It sells in your country (or worldwide, during the worldwide step)
2. It's the right tier for the current step (specialty first, then big shops)
3. It sells the kind of product you asked for, **or** it's a general shop that sells everything (eMAG, Amazon, eBay)

If the AI can't tell which category a product belongs to, every shop is searched, just like before categories existed.

### The categories

| Category | Typical products |
|---|---|
| `electronics` | laptops, phones, TVs, headphones, cameras |
| `appliances` | fridges, washing machines, vacuum cleaners, coffee machines |
| `gaming` | consoles, video games, gaming accessories |
| `fashion` | clothes, shoes, watches, bags |
| `beauty` | perfume, make-up, skincare |
| `health` | vitamins, supplements, pharmacy products |
| `sports` | sports equipment and sportswear |
| `cycling` | bikes and bike parts |
| `outdoor` | camping, hiking, fishing |
| `books` | books and e-books |
| `home` | furniture, bedding, decorations |
| `diy` | tools, paint, garden, building materials |
| `pets` | pet food and supplies |
| `toys` | toys and board games |
| `baby` | strollers, baby bottles, baby care |
| `music` | instruments and studio gear |
| `auto` | car parts and accessories |
| `general` | marketplaces and department stores that sell everything (always included) |

### Adding a shop

No code change is needed. Add a row to `supported_retailers`:

```sql
INSERT INTO supported_retailers (domain, target_country, requires_proxy, tier, category)
VALUES ('example-shop.ro', 'RO', FALSE, 'niche', '{electronics,appliances}');
```

The server reloads the shop list every 5 minutes.

---

## How SmartShop Reads Shop Websites

Reading a shop's page automatically is called **scraping**. Many shops don't like being scraped and try to block automated visitors. SmartShop tries up to three ways to get each page and stops at the first one that works:

```
 ① Visit directly ............ free, works for most small and mid-sized shops
        │ blocked?
        ▼
 ② Visit through a proxy ..... a home internet connection; costs a little; optional
        │ still blocked?
        ▼
 ③ Use a saved copy .......... the Internet Archive; rarely has recent product pages
```

**It learns.** When a shop blocks the direct visit, SmartShop remembers this in the `hostile_domains` table and goes straight to the proxy next time, even after a restart.

**It behaves like a normal visitor**, which reduces blocking:

- It looks like one of six real versions of Chrome or Edge, and always the *same* one for the same shop, because a real person doesn't switch browsers between clicks.
- It says it speaks the shop's language (Romanian for `.ro` shops, German for `.de` and so on, across 21 countries).
- It sends the shop's own address as the "previous page", the way a real visitor clicking around would.
- After a "too many requests" reply it waits 2–4 seconds and retries once. After a "forbidden" reply it waits and retries once as a different browser version.

**It spots fake pages.** Some shops return an empty page instead of an error when they block you. Pages that are suspiciously small and contain no product data are treated as blocked.

**It finds the facts in a reliable way.** Most shops hide a tidy summary of the product inside the page for Google (price, stock, rating, brand). SmartShop reads that summary first, which is far more reliable than guessing the price from marketing text. It also checks other common hidden data and the visible "Add to cart" button.

**It understands "out of stock" in 20+ languages**, so sold-out products are removed before scoring.

**What still doesn't work:** some shops only show their products after your browser runs their code (carturesti.ro, for example). SmartShop doesn't run a real browser, so those pages come back empty.

<details>
<summary><b>Technical details</b></summary>

- Fetching: `curl_cffi` with six impersonation profiles (`chrome131`, `chrome124`, `chrome120`, `chrome116`, `chrome110`, `edge101`), chosen per domain by an MD5 hash, with hand-picked overrides for some sites.
- Escalation: HTTP 403/503/429 or a soft block (< 5 KB, or 5–15 KB with no JSON-LD / `__NEXT_DATA__` / Vue state) triggers the proxy. Domains with `requires_proxy=TRUE` or listed in `hostile_domains` skip the direct attempt.
- Proxy: IPRoyal (`geo.iproyal.com:12321`). If no proxy is configured, a blocked page is simply marked as blocked.
- Product-page filter: `is_likely_product_url()` rejects category, search, filter, blog and account URLs using a multilingual pattern list, and accepts URLs with a SKU/ID, a CMS product prefix (`/products/`, `/pd/`, `/dp/`, `/p/1234`), or enough path depth and a descriptive slug.
- Extraction: `jsonld_service.extract_jsonld_facts` (Schema.org JSON-LD and microdata) and `extract_bs4_facts` (Open Graph meta tags, `itemprop`, `aria-label` star ratings, `data-price` attributes). JSON-LD wins on conflict. Both are cached with `functools.lru_cache(256)`.
- Buy buttons: form contents are reduced to the text of their *enabled* buttons. Disabled "Add to cart" buttons count as an out-of-stock signal.

</details>

---

## How Products Are Scored

Every product gets four scores from 0 to 100, which are combined into one **value score**:

| Score | Weight | What it means |
|---|---|---|
| **Cost efficiency** | 40% | Is it good value for the money? Being well under budget is rewarded. |
| **Quality** | 35% | How good is it? Star rating, number of reviews, specifications. |
| **Delivery** | 15% | Shipping cost, delivery speed, whether it ships to you. |
| **Trust** | 10% | Is the seller reputable? Is there a fair return policy? |

```
value score = cost × 0.40 + quality × 0.35 + delivery × 0.15 + trust × 0.10
```

How to read a score:

- **40** means "no information found". It counts as unknown, not as bad.
- **0** means confirmed bad news, such as out of stock, over budget or a suspicious seller.
- **100** means confirmed excellent, such as 4.5+ stars with hundreds of reviews, or same-day delivery.

**The AI gives the four scores, but plain code does the maths.** AI models are surprisingly bad at arithmetic, so SmartShop throws away the AI's total and recalculates it. It also fixes scores accidentally given on a 0–1 scale instead of 0–100, keeps every score between 0 and 100, and re-sorts the list.

**Cut-off answers are rescued.** If Gemini's answer is cut off partway through, SmartShop keeps every product that arrived complete. Only if none did does it ask OpenAI to score instead.

**Made-up links are removed.** Any product whose link wasn't actually found during the search is dropped, so you never get a link to a page that doesn't exist.

**Before scoring, a product must look buyable**: either the shop's own data says "In Stock", or the page has a working "Add to cart" / "Adaugă în coș" / "In den Warenkorb" style button.

**Budget:** products up to 20% over your budget can still be considered (a great deal at 2100 RON might be worth it on a 2000 RON budget). Anything above that is removed.

**"Find me something cheaper":** SmartShop takes the cheapest product it just showed you and sets the new budget to 80% of that price. For example, if the cheapest was 1600 RON, the new limit is 1280 RON.

### Delivery information

Product pages rarely say what shipping costs, so SmartShop goes looking:

1. It scans the page footer for links like "Shipping", "Livrare", "Versand" or "Livraison".
2. It reads that policy page with Gemini and fills in a fixed form: does it ship to your country, how much does it cost, how many days does it take, and is there a free-shipping threshold.
3. Foreign prices are converted roughly into your currency (for example, 1 EUR ≈ 5 RON).

This is done once per shop, not once per product, so three products from the same shop only cost one lookup.

---

## How SmartShop Stays Fast

| Technique | In plain words |
|---|---|
| **Search memory (6 hours)** | Similar searches made in the last 6 hours return instantly. Searches are matched by meaning (92% similarity), not by exact wording. |
| **Page memory (24 hours)** | Downloaded pages are saved in the database for 24 hours, so popular products aren't downloaded again and again. |
| **"Already seen" list** | A compact list in memory (about 120 KB for 100,000 pages) that quickly answers "have we downloaded this page before?" |
| **Recent pages in memory** | The 2,000 most recently downloaded pages are kept in memory for instant reuse. |
| **Reading results reused** | If the same page is analysed twice, the second time is instant. |
| **Queue with priorities** | Live user searches go first with no delay. Background work waits politely so shops aren't overloaded. |
| **Parallel work** | Pages are downloaded side by side (12 at a time), not one after another. The community research runs while the main search is happening. |
| **Shop list memory** | The list of shops is reloaded from the database every 5 minutes, not on every search. |

<details>
<summary><b>Technical details</b></summary>

- Search memory: `cache_service` stores 768-dimension Gemini embeddings in the `search_cache` table and looks them up with the `find_similar_search` SQL function (cosine similarity ≥ 0.92, same category, compatible budget, not expired). It's skipped when `excluded_urls` is set or `is_refinement=true`.
- "Already seen" list: a Bloom filter (`capacity=100_000`, `error_rate=0.01`) using Kirsch-Mitzenmacher double hashing (MD5 + SHA-1). It never says "no" for a page it has seen; about 1 in 100 unseen pages get a false "yes", which is harmless because the next memory check misses and the page is downloaded anyway.
- Recent pages: `_LRUCache(maxsize=2000)` backed by `OrderedDict`.
- Queue: `ScraperScheduler`, an `asyncio.PriorityQueue` with 12 workers. Delay after each task: P1 user request 0 s, P2 retry 0.5 s, P3 prefetch 1 s, P4 cache refresh 2 s, P5 background 3 s.
- Admins can wipe all caches with `POST /search/admin/clear-cache` (only for emails listed in `ADMIN_EMAILS`).

</details>

---

## The Two AI Models and How They Work Together

SmartShop uses AI models from two different companies. Each one checks or backs up the other, so the app keeps working if one of them has an outage.

| Job | Main model | Backup if it fails |
|---|---|---|
| Understand your message | OpenAI `gpt-4o-mini` | Gemini 2.5 Flash |
| Score and rank products | Gemini 2.5 Flash | OpenAI `gpt-4o-mini` |
| Double-check the top picks | OpenAI `gpt-4o-mini` | Skipped; Gemini's picks are kept |
| Community recommendations | Gemini 2.5 Flash (with Google Search) | Skipped |
| Read delivery policies | Gemini 2.5 Flash | Skipped; delivery counts as "unknown" |
| Explain why nothing was found | Gemini 2.5 Flash | A generic message |
| Search memory | Gemini Embedding 001 | — |

Both models get **exactly the same instructions** for understanding your message, so they return answers in the same format and can stand in for each other. If neither is available, SmartShop politely asks you to try again in a few seconds.

---

## The Website (Frontend)

### Pages

| Address | Who can see it | What it's for |
|---|---|---|
| `/login` | Everyone | Sign in with email + fingerprint/face |
| `/register` | Everyone | Create an account (email, phone, city, country) |
| `/register/passkey` | Everyone | Set up your fingerprint/face login |
| `/verify` | Everyone | Fallback for email login links |
| `/dashboard` | Signed-in users | The chat where you search |
| `/history` | Signed-in users | Your last 50 conversations |

### The chat

- **Live progress messages** while searching, in your language.
- **Typing indicator** (three bouncing dots) while waiting.
- **Photo upload.** Attach a photo of a product. It's shrunk on your device before sending, to save time.
- **"Not satisfied?" button** under the latest results. It searches again and skips the products you already saw.
- The full conversation is sent with each message, so follow-ups like "cheaper" or "in black" work.

### Product cards

- Full product name and price
- Value score badge: **green** (80+), **yellow** (60–79), **red** (under 60)
- Four coloured bars for cost, quality, delivery and trust
- The AI's explanation, shortened to 3 lines with a button to expand it
- A **"View Product"** link that opens the shop's page, where you buy it yourself

---

## Database

All data lives in Supabase (PostgreSQL). Only the server can read or write it; the website never talks to the database directly. Row Level Security is switched on for every table.

| Table | What it stores |
|---|---|
| `profiles` | Your email, phone, city, state (optional) and country |
| `passkeys` | The public half of your passkey (never your fingerprint or face) |
| `chat_history` | Your messages and the results you were shown |
| `search_cache` | Recent search results, matched by meaning, kept for 6 hours |
| `scrape_cache` | Recently downloaded product pages, kept for 24 hours |
| `hostile_domains` | Shops that blocked direct visits, so the proxy is used next time |
| `supported_retailers` | The list of shops, with country, tier, categories and whether they need the proxy |

### Database changes (migrations), in order

| File | What it does |
|---|---|
| `001_initial_schema.sql` | Creates `profiles` and `passkeys` |
| `003_search_cache.sql` | Creates the search memory (`search_cache`, with pgvector) and `chat_history` |
| `004_simplify_profiles.sql` | Removes street address and postal code (no longer collected) |
| `005_supported_retailers.sql` | Creates the shop list and adds the first 100+ shops |
| `006_scrape_cache.sql` | Creates the page memory and the "blocked shops" list |
| `007_drop_plan_columns.sql` | Removes the old paid-plan columns |
| `008_retailer_tiers.sql` | Adds the specialty/big-shop tier |
| `009_niche_retailer_expansion.sql` | Adds many more specialty shops across all countries |
| `010_modify_certain_domain_flags.sql` | Marks shops with strong bot protection as "needs proxy" |
| `011_retailer_categories.sql` | Adds the **category** column, tags every known shop, and adds 33 more Romanian shops |

There is no `002` migration; the numbering simply skips it.

---

## Project Structure

```
SmartShoppingAssistant/
├── README.md                          This file
├── CLAUDE.md                          Original architecture notes (includes the unbuilt checkout plan)
│
├── backend/                           The server (Python)
│   ├── main.py                        Starts the server, loads the shop list on startup
│   ├── requirements.txt               Python packages needed
│   ├── live_pipeline_test.py          Runs 5 real searches with detailed logs (costs API credits)
│   ├── core/config.py                 Reads settings from .env
│   ├── models/
│   │   ├── search.py                  Shapes of chat messages, products and responses
│   │   └── user.py                    Shapes of login/registration data
│   ├── routers/
│   │   ├── auth.py                    Login, registration, passkeys, admin check
│   │   └── search.py                  The search pipeline (steps ①–⑦), history, cache clearing
│   ├── services/
│   │   ├── openai_router.py           OpenAI: understand messages, double-check picks, backup scoring
│   │   ├── gemini_service.py          Gemini: scoring, community research, delivery policies,
│   │   │                                embeddings, and the shared instructions for both models
│   │   ├── tavily_service.py          Finds product pages on the web
│   │   ├── scraper_service.py         Downloads pages (direct → proxy → archive), spots blocks,
│   │   │                                filters non-product pages, memory caches, queue
│   │   ├── jsonld_service.py          Pulls price, stock, rating out of a page
│   │   ├── retailers_service.py       Shop list: picks shops by country, tier and category
│   │   ├── cache_service.py           The 6-hour search memory
│   │   ├── supabase_service.py        Connection to the database
│   │   └── logistics_data.py          Old fixed shipping table (no longer used)
│   └── tests/                         Automatic tests
│       ├── mock/                      Fast tests with all outside services faked
│       ├── live/                      Slow tests that use real services (cost credits)
│       └── test_*.py                  Login, registration, scraper and proxy tests
│
├── frontend/                          The website (Next.js)
│   ├── app/
│   │   ├── (auth)/                    login, register, register/passkey, verify
│   │   └── (dashboard)/               dashboard (chat), history
│   ├── components/
│   │   ├── auth/                      Login and registration forms, passkey setup
│   │   ├── chat/                      Chat window, message bubbles, input box, product cards
│   │   └── ThemeToggle.tsx            Light/dark switch
│   ├── lib/
│   │   ├── api.ts                     Talks to the server
│   │   ├── webauthn.ts                Talks to the fingerprint/face sensor
│   │   └── imageCompressor.ts         Shrinks photos before upload
│   └── __tests__/                     Automatic tests for the website
│
├── supabase/migrations/               Database changes, applied in order (see above)
│
└── cloudflare-worker/                 Old proxy code, no longer used
```

---

## Running It on Your Computer

### What you need

- **Python 3.12 or newer** and **Node.js 20 or newer**
- A free **Supabase** project with the `vector` extension switched on
- API keys for **Gemini**, **Tavily** and **OpenAI**
- *(Optional)* **IPRoyal** proxy login details, for shops that block direct visits

### 1. Set up the database

Apply every file in `supabase/migrations/` in number order. The easiest way is the Supabase command-line tool, linked to your project:

```bash
npx supabase db push
```

Alternatively, paste each file into the Supabase SQL editor, in order.

### 2. Start the server

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # on Windows: .venv\Scripts\activate
pip install -r requirements.txt
# create backend/.env (see "Settings" below)
uvicorn main:app --reload          # runs on http://localhost:8000
```

### 3. Start the website

```bash
cd frontend
npm install
# create frontend/.env.local with:  NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev                        # runs on http://localhost:3000
```

Open **http://localhost:3000** in your browser, register, and start chatting.

---

## Settings (Environment Variables)

Settings and secret keys go in a file called `.env`. **Never commit these files or share them.** They contain keys that cost money if someone else uses them.

### Server (`backend/.env`)

```env
# ── Required ───────────────────────────────────────────────────────────────
SUPABASE_URL=https://<your-project>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=...      # full-access database key — keep secret
SUPABASE_ANON_KEY=...
GEMINI_API_KEY=...
TAVILY_API_KEY=...
JWT_SECRET=...                     # any long random text (32+ characters)

# ── Recommended ────────────────────────────────────────────────────────────
OPENAI_API_KEY=...                 # without it, Gemini does everything alone

# ── Optional ───────────────────────────────────────────────────────────────
RP_ID=localhost                    # your site's domain name (for passkeys)
RP_NAME=SmartShop Assistant        # name shown when creating a passkey
FRONTEND_ORIGIN=http://localhost:3000
ADMIN_EMAILS=you@example.com       # comma-separated; who may clear the caches.
                                   # Empty = nobody (the safe default)

# Residential proxy, for shops that block direct visits
PROXY_HOST=geo.iproyal.com
PROXY_PORT=12321
PROXY_USERNAME=...
PROXY_PASSWORD=...
```

### Website (`frontend/.env.local`)

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

The website no longer needs Supabase keys; it only talks to the server.

---

## Running the Tests

### Fast tests (no API keys, no internet, a few seconds)

```bash
cd backend
python -m pytest -m "not live" -q
```

These fake every outside service (AI, search, database, shops), so they're free and fast. They cover login and registration, the full search flow with realistic conversations, shop selection by category, scoring maths, page reading, the memory caches, the admin check and the fallbacks.

### Website tests

```bash
cd frontend
npm test
```

### Live tests (use real services and cost API credits)

```bash
cd backend
python -m pytest -m live tests/live/test_niche_scraper_live.py -v -s   # real shop pages
python -m pytest -m live tests/live/test_search_live.py -v              # real AI + search
python live_pipeline_test.py                                            # 5 full searches, detailed logs
```

Some live tests only run when you set an extra switch, because they're expensive:
`RUN_FULL_PIPELINE_TESTS=1`, `RUN_NICHE_PIPELINE_TESTS=1`, `RUN_NICHE_COMPARISON=1`.

---

## Known Limitations

- **No automatic buying.** You buy on the shop's own website.
- **Some shops can't be read.** Shops that build their pages in the browser (for example carturesti.ro), or that block both direct visits and the proxy (for example notino.ro), return nothing.
- **The Internet Archive rarely helps** for product pages, because it seldom has recent copies.
- **The proxy costs money** and may stop working if the account runs out of credit.
- **New shops were added from general knowledge.** The 33 Romanian shops added in migration 011 haven't each been checked to confirm they're online and readable. Shops that block SmartShop are marked automatically after the first failed visit.
- **AI answers can vary.** The same search can give slightly different picks on different days, because shop stock and prices change and AI models aren't perfectly consistent.

---

## Design Rules

These rules guided how SmartShop was built:

1. **Card details are never stored.** SmartShop never asks for or keeps payment details. You pay on the shop's own website.
2. **The maths is done by code, not AI.** The final value score is always recalculated in Python, so a confused AI (or a shop page trying to trick it) can't change the ranking.
3. **Only real links.** A product is only shown if its link was actually found during the search.
4. **The shop list lives in the database.** Adding, removing or re-categorising a shop is a database change, not a code change.
5. **Always a fallback.** Every outside service (each AI model, the proxy, the caches) can fail without breaking the search. The app degrades gracefully instead of showing an error.
6. **Tests don't touch real services.** The fast test suite fakes everything, so it's free and works offline.

---

## Glossary

| Term | Meaning |
|---|---|
| **API key** | A secret password that lets SmartShop use a paid service such as OpenAI or Gemini |
| **Backend / server** | The part of the app that runs on a computer somewhere and does the actual work |
| **Cache** | A short-term memory that saves results so they don't have to be fetched again |
| **Embedding** | A list of numbers that captures the *meaning* of a piece of text, so similar texts get similar numbers |
| **Frontend** | The part of the app you see in your browser |
| **JSON-LD** | A tidy, hidden summary of a product (price, stock, rating) that shops put on their pages for Google |
| **JWT / token** | A digital pass that proves you're logged in, valid for 24 hours |
| **Migration** | A file that changes the structure of the database, applied in order |
| **Passkey** | A login that uses your fingerprint, face or device PIN instead of a password |
| **Proxy (residential)** | A middleman that sends a request through a normal home internet connection, so the shop sees an ordinary visitor |
| **Scraping** | Automatically downloading a web page and reading information from it |
| **Specialty / niche shop** | A smaller shop focused on one kind of product, such as cycling gear or books |
| **Mainstream shop** | A big marketplace that sells a bit of everything, such as eMAG or Amazon |
| **Tier** | Whether a shop is a specialty (niche) shop or a big (mainstream) shop |

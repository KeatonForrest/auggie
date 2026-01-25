# Auggie - Frequently Asked Questions

## General

### What is Auggie?
Auggie is an AI-powered account research tool for sales teams. Enter a company URL, and in 60 seconds you get a complete research document with company overview, tech stack, recent news, key contacts, pain points, and personalized talking points.

### Who is Auggie for?
- SDRs (Sales Development Reps)
- AEs (Account Executives)
- Sales teams doing outbound prospecting
- Anyone who needs to research companies before outreach

### How long does it take?
About 60 seconds per company. What used to take 30-60 minutes of manual research is done automatically.

---

## How is Auggie different from ChatGPT or Claude?

### 1. Real-time data, not training data
**ChatGPT/Claude:** Has a knowledge cutoff. Can't tell you what a company announced last week or what jobs they're hiring for today.

**Auggie:** Actually scrapes the company's website, job boards, and news in real-time. Every research document reflects what's happening *right now*.

### 2. Actual tech stack detection
**ChatGPT/Claude:** Can only guess what technologies a company uses based on general knowledge. Often wrong or outdated.

**Auggie:** Uses Wappalyzer to analyze the actual code running on their website. Detects frameworks, databases, analytics tools, and infrastructure with certainty.

### 3. One click, not prompt engineering
**ChatGPT/Claude:** You need to craft prompts, copy-paste website content, iterate on outputs, and manually structure the research.

**Auggie:** Paste a URL. Click a button. Done. No prompt engineering required.

### 4. Personalized to YOUR product
**ChatGPT/Claude:** Generic research. You'd need to explain your product every time and ask it to find relevant pain points.

**Auggie:** Knows what you're selling (from onboarding). Every research document automatically includes product fit analysis and talking points tailored to your specific solution.

### 5. Integrated data sources
**ChatGPT/Claude:** Can only work with what you paste into it. You'd need to manually gather data from multiple sources.

**Auggie:** Automatically pulls from:
- Company website (10+ pages)
- Job boards (Greenhouse, Lever, Ashby)
- News (Google News via SerpAPI)
- Contacts (Apollo.io)
- Tech detection (Wappalyzer)

All in one request.

### 6. Consistent, structured output
**ChatGPT/Claude:** Output format varies. Sometimes verbose, sometimes brief. Requires follow-up prompts to get what you need.

**Auggie:** Same structured format every time:
- Company Overview
- Tech Stack
- Hiring Signals
- Business Problems
- Product Fit
- Talking Points
- Key Contacts
- Recent News

### 7. Built for sales workflow
**ChatGPT/Claude:** General-purpose AI. You're adapting it to sales research.

**Auggie:** Purpose-built for account research. Generates email sequences. Exports to markdown. Integrates with your sales materials.

---

## The Bottom Line

| | ChatGPT/Claude | Auggie |
|--|----------------|--------|
| Data freshness | Months old | Real-time |
| Tech stack | Guesses | Actual detection |
| Setup time | 5-10 min of prompting | 5 seconds |
| Personalization | Manual each time | Built-in |
| Data sources | 1 (what you paste) | 5+ integrated |
| Output format | Variable | Consistent |
| Price | $20/mo + your time | $25/mo, no extra work |

**Think of it this way:** ChatGPT is a smart assistant you have to manage. Auggie is a research analyst who already knows what you need.

---

## Pricing

### How much does Auggie cost?
$24.99/month for 25 research documents. That's about $1 per account researched.

### Is there a free trial?
Yes - you get 5 free researches to try it out. No credit card required.

### What if I need more than 25 researches?
You can buy additional credit packs: $10 for 10 extra researches. Use them whenever you need them.

### Can I cancel anytime?
Yes. Monthly subscription with no commitment.

---

## Features

### What data sources does Auggie use?
- **Firecrawl** - Scrapes company websites (homepage, about, careers, blog)
- **Wappalyzer** - Detects technologies from website code
- **SerpAPI** - Fetches recent news from Google News
- **Apollo.io** - Finds key contacts and company info
- **Your materials** - References your uploaded sales collateral

### What's included in a research document?
1. Company Overview
2. Specific Projects & Initiatives
3. Confirmed Technology Stack
4. Technical Hiring Signals
5. Stated Business Problems
6. Product Fit Analysis
7. Recommended Talking Points
8. Key Contacts
9. Recent News
10. Information Gaps

### Can Auggie write emails for me?
Yes. After generating research, click "Write Outreach" to generate a personalized 3-email sequence based on the research.

### What file formats can I upload for materials?
PDF, DOCX, and PPTX. Upload case studies, battle cards, product docs, and sales decks. Auggie will automatically reference them in your research.

---

## Privacy & Security

### Do you store the research I generate?
Yes, research documents are saved to your account so you can access them later. Only you can see your research.

### Do you share my data?
No. Your research, materials, and account data are never shared with third parties.

### Is my data used to train AI models?
No. Your data is used only to generate your research documents.

---

## Technical

### What AI model does Auggie use?
Claude Opus 4 for research generation (highest quality reasoning) and Claude Sonnet 4 for email sequences.

### How accurate is the tech stack detection?
Very accurate. Wappalyzer analyzes the actual JavaScript, meta tags, and HTTP headers on the website. It detects what's actually running, not what the company claims to use.

### Why are some contact names partially hidden?
Apollo.io masks some contact details on their free/basic tiers. The titles and roles are still visible, which is what matters most for targeting.

---

## Support

### How do I get help?
Email support@auggie.tools or use the chat widget in the app.

### I found a bug. How do I report it?
Email us at support@auggie.tools with details about what happened. Screenshots help!

### Can I request a feature?
Absolutely. We love feedback. Email us or use the feedback form in the app.

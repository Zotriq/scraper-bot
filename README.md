# RAG Scraper Bot

![Python](https://img.shields.io/badge/Python-3.13-3776AB?style=flat-square&logo=python&logoColor=white)
![BeautifulSoup](https://img.shields.io/badge/BeautifulSoup-HTML%20parsing-4B8BBE?style=flat-square)

A parallel web scraper that collects pages and documents from a website and saves them in a clean,
organized structure, ready to load into a RAG knowledge base.

## What it does

1. **Discover URLs:** crawls a site and collects every internal page link, skipping images, archives and media
   (`url_explorer.ipynb`).
2. **Clean URLs:** fixes malformed links (for example `https:/www…` → `https://www…`) and removes duplicates.
3. **Extract content:** for each page, saves the readable text and downloads any linked files (PDFs, Word and Excel documents).
4. **Organize output:** each URL gets its own folder under `./downloads/`, named from the domain, path and a short hash,
   so pages never overwrite each other.
5. **Runs in parallel** with a thread pool, so large sites finish quickly.

## Getting started

```bash
pip install -r requirements.txt
```

- Put the URLs to process in `urls.txt`, or start from a homepage in `url_explorer.ipynb` to discover them.
- Run the notebook cells to scrape. Results are saved to `./downloads/`.

## Project structure

```
utils.py               URL cleaning, page extraction, file downloads
clean_url.py           URL normalization helpers
url_explorer.ipynb     Site crawler + parallel batch pipeline
scrapper.ipynb         Single-URL pipeline for testing
urls.txt               Input URL list
```

## Use responsibly

Only scrape sites you have permission to collect from, and follow each site's terms of service and `robots.txt`.

## Tech stack

Python · Requests · BeautifulSoup · concurrent.futures

#!/usr/bin/env python3
"""
Extract text from OCR PDFs and generate structured JSON catalog index.
Processes all ocr_trim_page_*.pdf files and creates catalog_index.json and section_index.json
"""

import json
import os
import re
import subprocess
from pathlib import Path
from collections import defaultdict

# Section mapping based on catalog TOC
SECTION_MAPPING = [
    ("Fastener_Anchoring_Systems", 3, 73),
    ("Fastening_Systems", 74, 91),
    ("Material_Handling_Storage", 92, 99),
    ("Hand_Tools", 100, 119),
    ("Measuring_Marking", 120, 131),
    ("Ladders", 132, 134),
    ("Cleaning_Supplies", 135, 143),
    ("Jobsite_Supplies", 144, 171),
    ("Building_Materials", 172, 184),
    ("Adhesives_Caulks", 185, 188),
    ("Power_Tools_Equipment_Accessories", 189, 246),
    ("Safety_Equipment_Supplies", 247, 298),
]

def get_section_info(page_num):
    """Determine section name and page range group for a given page number."""
    for section_name, start, end in SECTION_MAPPING:
        if start <= page_num <= end:
            # Format section name with proper spacing
            display_name = section_name.replace("_", " ")
            # Create page range group (groups of 10)
            range_start = (page_num // 10) * 10
            range_end = range_start + 9
            page_range = f"Pages {range_start}–{range_end}"
            return display_name, page_range
    return "Unknown", "Unknown"

def extract_text_from_pdf(pdf_path):
    """Extract text from PDF using pdftotext."""
    try:
        result = subprocess.run(
            ['pdftotext', '-layout', pdf_path, '-'],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Error extracting text from {pdf_path}: {e}")
        return ""

def clean_text(text):
    """Clean and normalize extracted text."""
    # Remove excessive whitespace
    text = re.sub(r'\s+', ' ', text)
    # Remove special characters that interfere with parsing
    text = text.replace('\x0c', ' ')  # form feed
    return text.strip()

def extract_title(text, page_num):
    """Generate a human-friendly page title from the text."""
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    # Look for major headings (uppercase text, longer than 5 chars)
    headings = []
    for line in lines[:30]:  # Check first 30 lines
        # Check if line is mostly uppercase and significant length
        if len(line) > 5 and sum(c.isupper() for c in line if c.isalpha()) / max(len([c for c in line if c.isalpha()]), 1) > 0.6:
            # Skip common non-title patterns
            if not any(skip in line.upper() for skip in ['CAT #', 'PART NO', 'SKU', 'DESCRIPTION', 'QTY', 'BOX']):
                headings.append(line.strip())
    
    if headings:
        # Take first 1-2 major headings
        title = " – ".join(headings[:2])
        # Limit length
        if len(title) > 80:
            title = title[:77] + "..."
        return title
    
    # Fallback: use first substantial line
    for line in lines[:20]:
        if len(line) > 10 and not line.startswith('CAT'):
            return line[:80]
    
    # Last resort
    section, _ = get_section_info(page_num)
    return f"{section} – Page {page_num}"

def extract_products(text):
    """Extract product names, model numbers, and major items."""
    products = []
    lines = text.split('\n')
    
    # Patterns to identify products
    product_patterns = [
        r'([A-Z][A-Za-z0-9\s\-&/]+(?:Gun|Nailer|Drill|Saw|Tool|Anchor|Fastener|Bit|System|Kit|Set))',
        r'([A-Z][A-Z\s]{5,})',  # Multiple uppercase words
        r'([A-Z0-9\-]{4,}[A-Z0-9])',  # Model numbers
    ]
    
    for line in lines[:50]:  # Focus on first part of page
        line = line.strip()
        if not line or len(line) < 4:
            continue
            
        # Skip table headers
        if any(header in line.upper() for header in ['CAT #', 'PART NO', 'SKU', 'DESCRIPTION', 'QTY', 'SIZE']):
            continue
        
        for pattern in product_patterns:
            matches = re.findall(pattern, line)
            for match in matches:
                match = match.strip()
                if len(match) > 4 and len(match) < 60:
                    # Clean up
                    match = re.sub(r'\s+', ' ', match)
                    if match not in products:
                        products.append(match)
    
    # Limit to top 10 most relevant
    return products[:10]

def extract_keywords(text, title, products):
    """Extract relevant keywords from text."""
    keywords = set()
    
    # Convert to lowercase for analysis
    text_lower = text.lower()
    
    # Common tool/product terms
    common_terms = [
        'drill', 'saw', 'nailer', 'hammer', 'wrench', 'pliers', 'screwdriver',
        'anchor', 'fastener', 'bolt', 'screw', 'nail', 'pin', 'rivet',
        'cordless', 'electric', 'pneumatic', 'manual', 'power tool',
        'concrete', 'steel', 'wood', 'metal', 'plastic',
        'safety', 'protective', 'gloves', 'glasses', 'mask',
        'measuring', 'tape', 'level', 'square',
        'ladder', 'scaffold', 'platform',
        'cleaning', 'supplies', 'chemical',
        'storage', 'box', 'cabinet', 'cart',
        'dewalt', 'milwaukee', 'hilti', 'stanley', 'red head'
    ]
    
    # Find terms in text
    for term in common_terms:
        if term in text_lower:
            keywords.add(term)
    
    # Extract from title
    title_words = re.findall(r'\b[a-z]{4,}\b', title.lower())
    keywords.update(word for word in title_words if word not in ['page', 'pages', 'catalog'])
    
    # Extract from products
    for product in products:
        product_words = re.findall(r'\b[a-z]{4,}\b', product.lower())
        keywords.update(product_words[:3])  # Limit per product
    
    return sorted(list(keywords))[:15]  # Limit to 15 keywords

def generate_summary(text, title, products):
    """Generate a 1-2 sentence summary of the page."""
    section_info = ""
    if products:
        if len(products) <= 3:
            product_list = ", ".join(products)
        else:
            product_list = f"{', '.join(products[:3])}, and {len(products) - 3} more"
        section_info = f"Features {product_list}. "
    
    # Analyze content type
    text_lower = text.lower()
    content_type = []
    
    if 'specifications' in text_lower or 'spec' in text_lower:
        content_type.append("specifications")
    if 'accessories' in text_lower:
        content_type.append("accessories")
    if 'model' in text_lower or 'cat #' in text_lower:
        content_type.append("product listings")
    if 'application' in text_lower or 'use' in text_lower:
        content_type.append("application details")
    
    content_desc = " and ".join(content_type) if content_type else "product information"
    
    summary = f"{section_info}This page includes {content_desc}."
    return summary

def process_pdf(pdf_path, page_num):
    """Process a single PDF and return structured data."""
    print(f"Processing page {page_num}...")
    
    # Extract text
    text = extract_text_from_pdf(pdf_path)
    if not text:
        print(f"  Warning: No text extracted from page {page_num}")
        text = ""
    
    text = clean_text(text)
    
    # Get section info
    section, page_range = get_section_info(page_num)
    
    # Extract components
    title = extract_title(text, page_num)
    products = extract_products(text)
    keywords = extract_keywords(text, title, products)
    summary = generate_summary(text, title, products)
    
    # Create entry
    entry = {
        "page": page_num,
        "filename": f"ocr_trim_page_{page_num:04d}.pdf",
        "thumbnail": f"thumbnails/page_{page_num:04d}.png",
        "section": section,
        "pageRangeGroup": page_range,
        "title": title,
        "products": products,
        "keywords": keywords,
        "summary": summary
    }
    
    return entry

def main():
    """Main processing function."""
    base_dir = Path(__file__).parent
    pdf_dir = base_dir / "pdf"
    
    print("=" * 60)
    print("Stanley Catalog Index Generator")
    print("=" * 60)
    
    # Find all PDF files
    pdf_files = []
    for section_dir in pdf_dir.iterdir():
        if section_dir.is_dir():
            for pdf_file in section_dir.glob("ocr_trim_page_*.pdf"):
                # Extract page number
                match = re.search(r'ocr_trim_page_(\d+)\.pdf', pdf_file.name)
                if match:
                    page_num = int(match.group(1))
                    pdf_files.append((page_num, pdf_file))
    
    # Sort by page number
    pdf_files.sort(key=lambda x: x[0])
    
    print(f"Found {len(pdf_files)} PDF files to process")
    print()
    
    # Process all PDFs
    catalog_entries = []
    section_groups = defaultdict(list)
    
    for page_num, pdf_path in pdf_files:
        entry = process_pdf(pdf_path, page_num)
        catalog_entries.append(entry)
        section_groups[entry["section"]].append(page_num)
    
    print()
    print("=" * 60)
    print("Generating JSON files...")
    
    # Save catalog_index.json
    catalog_output = base_dir / "catalog_index.json"
    with open(catalog_output, 'w', encoding='utf-8') as f:
        json.dump(catalog_entries, f, indent=2, ensure_ascii=False)
    print(f"✓ Created {catalog_output} ({len(catalog_entries)} entries)")
    
    # Generate section_index.json
    section_index = {}
    for section_name, start, end in SECTION_MAPPING:
        display_name = section_name.replace("_", " ")
        section_index[display_name] = {
            "range": f"{start}–{end}",
            "pages": section_groups.get(display_name, [])
        }
    
    section_output = base_dir / "section_index.json"
    with open(section_output, 'w', encoding='utf-8') as f:
        json.dump(section_index, f, indent=2, ensure_ascii=False)
    print(f"✓ Created {section_output} ({len(section_index)} sections)")
    
    print()
    print("=" * 60)
    print("✓ Catalog index generation complete!")
    print("=" * 60)
    
    # Print summary statistics
    print("\nSummary:")
    print(f"  Total pages processed: {len(catalog_entries)}")
    print(f"  Sections: {len(section_index)}")
    print(f"  Total products identified: {sum(len(e['products']) for e in catalog_entries)}")
    print(f"  Total keywords: {sum(len(e['keywords']) for e in catalog_entries)}")

if __name__ == "__main__":
    main()

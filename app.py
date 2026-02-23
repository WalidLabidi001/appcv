"""
CV Manager — Main Flask Application
A professional CV management and search platform.
"""

import os
import re
import json
import uuid
import hashlib
from datetime import datetime

from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, send_from_directory, jsonify, session
)
from functools import wraps
import requests
from werkzeug.utils import secure_filename

from database import init_db, insert_cv, get_all_cvs, get_cv_by_id, search_cvs, delete_cv, get_stats, update_cv, check_duplicate
import pdfplumber
import docx

# ── Configuration ──────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'cv-manager-3e-x9-secret-k23')

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
ALLOWED_EXTENSIONS = {'pdf', 'txt', 'docx'}
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

# Ensure upload directory exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ── Helpers ────────────────────────────────────────────────────────────────────
def allowed_file(filename):
    """Check if the file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def login_required(f):
    """Decorator to protect routes that require authentication."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            flash('Veuillez vous connecter pour accéder à cette page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def extract_text(filepath):
    """Extract text content from a PDF or TXT file."""
    ext = filepath.rsplit('.', 1)[1].lower()

    if ext == 'txt':
        encodings = ['utf-8', 'latin-1', 'cp1252']
        for encoding in encodings:
            try:
                with open(filepath, 'r', encoding=encoding) as f:
                    return f.read()
            except (UnicodeDecodeError, UnicodeError):
                continue
        return ""

    elif ext == 'pdf':
        try:
            text_parts = []
            with pdfplumber.open(filepath) as pdf:
                for page in pdf.pages:
                    # Try normal extraction
                    page_text = page.extract_text(x_tolerance=2, y_tolerance=2)
                    if not page_text:
                        # Try with more tolerance or different layout
                        page_text = page.extract_text(layout=True)
                    
                    if page_text:
                        text_parts.append(page_text)
            
            extracted_text = '\n'.join(text_parts).strip()
            
            # If still no text, check if it has objects at all (scanned check)
            if not extracted_text:
                return "[ERREUR: Le document semble être une image scannée ou est protégé par mot de passe. Le texte n'a pas pu être extrait automatiquement.]"
            
            return extracted_text
        except Exception as e:
            print(f"Erreur reading PDF with pdfplumber: {e}")
            return f"[ERREUR TECHNIQUE: {str(e)}]"

    elif ext == 'docx':
        try:
            doc = docx.Document(filepath)
            text_parts = [p.text for p in doc.paragraphs]
            return '\n'.join(text_parts).strip()
        except Exception as e:
            print(f"Erreur reading DOCX: {e}")
            return f"[ERREUR TECHNIQUE: {str(e)}]"

    return ""


def parse_cv_metadata(text):
    """
    Advanced CV metadata extraction from raw text.
    Extracts emails, phone numbers, names, specialty, and identifies skills/sections.
    """
    metadata = {
        'emails': [],
        'phones': [],
        'skills': [],
        'sections': [],
        'name': 'Inconnu',
        'specialty': 'À définir',
        'experience': '0'
    }

    if not text or not text.strip() or "[ERREUR" in text:
        return metadata

    # Extract emails
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    metadata['emails'] = list(set(re.findall(email_pattern, text)))

    # Extract phone numbers (more robust pattern)
    phone_pattern = r'(?:(?:\+|00)33|0)\s*[1-9](?:[\s.-]*\d{2}){4}|(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{2,4}[-.\s]?\d{2,4}(?:[-.\s]?\d{2,4})?'
    phones = re.findall(phone_pattern, text)
    
    # Filter out false positives (date ranges like 2018-2019, short numbers, etc.)
    year_range_pattern = re.compile(r'^\s*\d{4}\s*[-–]\s*\d{4}\s*$')
    year_pattern = re.compile(r'^\s*(19|20)\d{2}\s*$')
    filtered_phones = []
    for p in phones:
        p_clean = p.strip()
        digits_only = re.sub(r'\D', '', p_clean)
        # Must have at least 8 digits
        if len(digits_only) < 8:
            continue
        # Must NOT look like a year range (e.g. "2018-2019")
        if year_range_pattern.match(p_clean):
            continue
        # Must NOT be just a single year
        if year_pattern.match(p_clean):
            continue
        # Must start with +, 0, or ( to look like a real phone number
        if not re.match(r'^[\s]*[+0(]', p_clean):
            continue
        filtered_phones.append(p_clean)
    
    metadata['phones'] = list(set(filtered_phones))[:5]

    # Enhanced skill keywords
    skill_keywords = [
        'Python', 'JavaScript', 'Java', 'C++', 'C#', 'PHP', 'Ruby', 'Swift', 'TypeScript', 'Go', 'Rust', 'Kotlin', 'SQL', 
        'React', 'Angular', 'Vue', 'Django', 'Flask', 'Docker', 'Kubernetes', 'AWS', 'Azure', 'GCP', 'Terraform', 'Ansible'
    ]
    text_lower = text.lower()
    for skill in skill_keywords:
        if re.search(r'\b' + re.escape(skill.lower()) + r'\b', text_lower):
            metadata['skills'].append(skill)

    # Detect Name first to help with Specialty
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    name_index = -1
    
    # Skip words for name detection (academic & professional terms that are NOT names)
    skip_words = ['experience', 'expérience', 'formation', 'compétence', 'contact', 'profil', 
                 'adresse', 'email', 'tel', 'téléphone', 'www', 'http', '@', 'cv', 'curriculum',
                 'ingénieur', 'développeur', 'engineer', 'developer', 'manager', 'consultant',
                 'stage', 'poste', 'emploi', 'date', 'lieu', 'ville', 'pays',
                 'preparatory', 'préparatoire', 'cycle', 'physic', 'chemistry', 'math',
                 'national', 'diploma', 'diplôme', 'bachelor', 'master', 'licence',
                 'school', 'école', 'university', 'université', 'institute', 'institut',
                 'education', 'overview', 'profile', 'summary', 'objective',
                 'computer', 'science', 'engineering', 'industrial', 'degree',
                 'sfax', 'tunis', 'tunisia', 'france', 'paris', 'lyon']
    
    # Heuristic 0: Check for "Name | Title" or "Name – Title" format (very common in modern CVs)
    found_spec = False
    for i, line in enumerate(lines[:10]):
        # Check for separators: |, –, —, /
        for sep in ['|', '–', '—']:
            if sep in line:
                parts = line.split(sep, 1)
                name_part = parts[0].strip()
                title_part = parts[1].strip() if len(parts) > 1 else ''
                
                name_words = name_part.split()
                # Validate name part: 2-3 words, reasonable length
                if 2 <= len(name_words) <= 3 and len(name_part) < 40:
                    # Check it looks like a name (capitalized words, no skip words)
                    if not any(sw in name_part.lower() for sw in skip_words):
                        if all(w[0].isupper() for w in name_words if w):
                            metadata['name'] = name_part
                            name_index = i
                            # Also grab the title from the other side of the separator
                            if title_part and len(title_part) > 3:
                                metadata['specialty'] = title_part
                                found_spec = True
                            break
            if name_index != -1:
                break
        if name_index != -1:
            break
    
    # Heuristic 1: Standard line-by-line name detection
    if name_index == -1:
        for i, line in enumerate(lines[:15]):
            words = line.split()
            # Name pattern: 2-3 words, reasonable length
            if 2 <= len(words) <= 3 and len(line) < 50:
                if any(sw in line.lower() for sw in skip_words):
                    continue
                
                # Pattern 1: "Prénom Nom" or "Prénom Nom Nom" (Title case)
                if re.match(r'^[A-ZÀ-Ÿ][a-zà-ÿ\-]+\s+[A-ZÀ-Ÿ][a-zà-ÿ\-]+(?:\s+[A-ZÀ-Ÿ][a-zà-ÿ\-]+)?$', line):
                    metadata['name'] = line
                    name_index = i
                    break
                
                # Pattern 2: "PRÉNOM NOM" (ALL CAPS - very common in CVs)
                if re.match(r'^[A-ZÀ-Ÿ\-]{2,}\s+[A-ZÀ-Ÿ\-]{2,}(?:\s+[A-ZÀ-Ÿ\-]{2,})?$', line):
                    metadata['name'] = line.title()
                    name_index = i
                    break
                
                # Pattern 3: Mixed - "PRÉNOM Nom" or "Prénom NOM"
                if re.match(r'^[A-ZÀ-Ÿa-zà-ÿ\-]{2,}\s+[A-ZÀ-Ÿa-zà-ÿ\-]{2,}(?:\s+[A-ZÀ-Ÿa-zà-ÿ\-]{2,})?$', line):
                    if any(w[0].isupper() for w in words):
                        common_words = ['les', 'des', 'pour', 'dans', 'avec', 'sur', 'par', 'une', 'the', 'and', 'for']
                        if not any(w.lower() in common_words for w in words):
                            metadata['name'] = ' '.join(w.capitalize() if w.isupper() and len(w) > 2 else w for w in words)
                            name_index = i
                            break

    # Detect Specialty (Job Title) - skip if already found from "Name | Title" format
    
    # Heuristic 1: Check lines immediately after the name (very high accuracy for CVs)
    if not found_spec and name_index != -1 and name_index + 1 < len(lines):
        for i in range(name_index + 1, min(name_index + 4, len(lines))):
            potential_title = lines[i]
            # A job title is usually one line, not too long, no period at end
            if 3 < len(potential_title) < 80 and not potential_title.endswith('.'):
                title_keywords = ['ingénieur', 'développeur', 'engineer', 'developer', 'analyst', 'manager', 'designer', 
                                 'consultant', 'architecte', 'technicien', 'expert', 'specialist', 'scientist', 'lead', 
                                 'directeur', 'data', 'devops', 'cloud', 'fullstack', 'full stack', 'backend', 'frontend',
                                 'mobile', 'sécurité', 'security', 'réseau', 'network', 'système', 'system', 'admin',
                                 'integration', 'intégration', 'bi ', 'business intelligence']
                if any(kw in potential_title.lower() for kw in title_keywords):
                    metadata['specialty'] = potential_title
                    found_spec = True
                    break

    # Heuristic 2: Predefined list of specialties (Fallback) - ordered from most specific to least
    if not found_spec:
        specialties = [
            # Most specific compound titles first
            'Data Integration Engineer', 'Machine Learning Engineer', 
            'Data Scientist', 'Data Analyst', 'Data Engineer',
            'Business Intelligence', 'BI Developer', 'BI Analyst',
            'Site Reliability Engineer', 'Full Stack Developer', 'Fullstack Developer',
            'Développeur Fullstack', 'Développeur Full Stack',
            'Ingénieur Data', 'Ingénieur Cloud', 'Ingénieur DevOps', 'Ingénieur Système',
            'Ingénieur Réseau', 'Ingénieur Sécurité', 'Ingénieur Logiciel',
            'Cloud Engineer', 'Cloud Architect', 'Security Engineer',
            'Développeur Backend', 'Backend Developer', 'Développeur Frontend', 'Frontend Developer',
            'Développeur Mobile', 'iOS Developer', 'Android Developer',
            'Chef de projet', 'Project Manager', 'Product Manager', 'Scrum Master',
            'UX Designer', 'UI Designer', 'UX/UI Designer', 'UX/UI',
            # Then generic single-word titles last
            'DevOps', 'SysOps',
            'Développeur', 'Ingénieur', 'Designer', 'Consultant', 'Architecte', 
            'Manager', 'Analyste', 'Administrateur', 'Technicien', 
            'Commercial', 'Comptable', 'RH', 'Marketing'
        ]
        
        # First search in the header/top of CV (more likely to be THE specialty)
        header_text = text_lower[:500]
        for spec in specialties:
            if spec.lower() in header_text:
                metadata['specialty'] = spec
                found_spec = True
                break
        
        # Then search in rest of document
        if not found_spec:
            for spec in specialties:
                if spec.lower() in text_lower:
                    metadata['specialty'] = spec
                    break

    # Extract Years of Experience
    # 1. Look for explicit mentions like "X ans d'expérience"
    exp_patterns = [
        r'(\d+)\s*(?:ans|années?)\s*d\'exp[eé]rience',
        r'(\d+)\s*(?:ans|ann[eé]es?)\s*exp',
        r'exp[eé]rience\s*(?:professionnelle)?\s*[:\s-]*\s*(\d+)\s*(?:ans|ann)',
        r'plus\s*de\s*(\d+)\s*(?:ans|ann)',
        r'expertise\s*[:\s-]*\s*(\d+)\s*(?:ans|ann)',
        r'(\d+)\s*(?:years?|yrs)\s*(?:of\s*)?exp',
        r'(\d+)\s*(?:years?|yrs)\s*(?:of\s*)?experience',
        r'senior\s*\(\s*(\d+)\s*\+\s*ans\s*\)',
    ]
    
    for pattern in exp_patterns:
        match = re.search(pattern, text_lower)
        if match:
            metadata['experience'] = match.group(1)
            break
    
    # Extract Years of Experience
    # 1. Look for explicit mentions like "X ans d'expérience"
    exp_patterns = [
        r'(\d+)\s*(?:ans|années?)\s*d\'exp[eé]rience',
        r'(\d+)\s*(?:ans|ann[eé]es?)\s*exp',
        r'exp[eé]rience\s*(?:professionnelle)?\s*[:\s-]*\s*(\d+)\s*(?:ans|ann)',
        r'plus\s*de\s*(\d+)\s*(?:ans|ann)',
        r'expertise\s*[:\s-]*\s*(\d+)\s*(?:ans|ann)',
        r'(\d+)\s*(?:years?|yrs)\s*(?:of\s*)?exp',
        r'(\d+)\s*(?:years?|yrs)\s*(?:of\s*)?experience',
        r'senior\s*\(\s*(\d+)\s*\+\s*ans\s*\)',
    ]
    
    for pattern in exp_patterns:
        match = re.search(pattern, text_lower)
        if match:
            metadata['experience'] = match.group(1)
            break
    
    # 2. Advanced Heuristic: Sum of Clean Work Durations
    if metadata['experience'] == '0':
        import datetime
        now = datetime.datetime.now()
        current_year, current_month = now.year, now.month
        
        months_map = {
            'jan': 1, 'fév': 2, 'mar': 3, 'avr': 4, 'mai': 5, 'jui': 6, 
            'jul': 7, 'aoû': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'déc': 12,
            'feb': 2, 'apr': 4, 'jun': 6, 'aug': 8
        }
        
        # Comprehensive academic and non-professional filters
        academic_keywords = [
            'université', 'university', 'master', 'licence', 'bachelor', 'baccalauréat', 'bac ', 'bac+',
            'diplôme', 'école', 'school', 'formation', 'étudiant', 'student', 'enseignement', 'degree',
            'cursus', 'académique', 'education', 'msc ', 'phd', 'doctorat', 'professeur', 'professor',
            'enseignant', 'assistant', 'lecturer', 'stage', 'internship', 'trainee', 'apprenti'
        ]
        
        month_regex = r'(?:janvier|f[eé]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[eé]cembre|january|february|march|april|may|june|july|august|september|october|november|december|janv?|f[eé]vr?|mar|apr|jun|jul|aug|sep|oct|nov|d[eé]c)'
        year_regex = r'\b(?:20[0-2]\d|19[7-9]\d)\b'
        present_regex = r'(?:pr[eé]sent|aujourd|maintenant|today|actuel|en cours|now)'
        range_pattern = rf'({month_regex})?\s*({year_regex})\s*[-–—àau]t?o?\s*({present_regex}|(?:({month_regex})?\s*({year_regex})))'
        
        lines = text.split('\n')
        periods = []
        
        # Pass 1: Collect date ranges while avoiding academic lines
        for i, line in enumerate(lines):
            low_line = line.lower()
            
            # Context check: check this line and 3 lines above for academic keywords
            context_text = ""
            for j in range(max(0, i-3), i+1):
                context_text += lines[j].lower() + " "
            
            if any(kw in context_text for kw in academic_keywords):
                continue # Skip academic entries
            
            matches = re.finditer(range_pattern, low_line)
            for m in matches:
                m1_str, y1_str, end_part, m2_str, y2_str = m.groups()
                y1 = int(y1_str)
                m1 = months_map.get(m1_str[:3] if m1_str else '', 1)
                
                if any(p in str(end_part) for p in ['present', 'aujourd', 'maintenant', 'today', 'actuel', 'en cours', 'now']):
                    y2, m2 = current_year, current_month
                elif y2_str:
                    y2 = int(y2_str)
                    m2 = months_map.get(m2_str[:3] if m2_str else '', 1)
                else:
                    continue
                
                duration = (y2 - y1) * 12 + (m2 - m1)
                if 0 < duration < 480: # Max 40 years
                    periods.append((y1 * 12 + m1, y2 * 12 + m2))
        
        # Pass 2: Merge overlapping periods
        if periods:
            periods.sort()
            merged_months = 0
            curr_start, curr_end = -1, -1
            for start, end in periods:
                if curr_start == -1:
                    curr_start, curr_end = start, end
                elif start <= curr_end:
                    curr_end = max(curr_end, end)
                else:
                    merged_months += (curr_end - curr_start)
                    curr_start, curr_end = start, end
            merged_months += (curr_end - curr_start)
            metadata['experience'] = str(max(1, round(merged_months / 12)))
        
        # Pass 3: Fallback (Earliest Year) - only if still 0
        if metadata['experience'] == '0':
            all_work_years = []
            for line in lines:
                low_line = line.lower()
                if not any(kw in low_line for kw in academic_keywords):
                    years = re.findall(year_regex, low_line)
                    all_work_years.extend([int(y) for y in years])
            
            if all_work_years:
                valid = [y for y in all_work_years if 1980 < y <= current_year]
                if valid:
                    metadata['experience'] = str(current_year - min(valid))

    # Detect sections
    section_patterns = [
        r'(?i)(exp[eé]riences?\s*(?:professionnelles?)?)',
        r'(?i)(formations?\s*(?:acad[eé]miques?|diplomes?)?)',
        r'(?i)(comp[eé]tences?)',
        r'(?i)(education|academic|skills|languages|projets|hobbies|profil)',
    ]

    for pattern in section_patterns:
        matches = re.findall(pattern, text)
        if matches:
            val = matches[0]
            if isinstance(val, tuple): val = val[0]
            metadata['sections'].append(val.strip().title())

    metadata['sections'] = list(set(metadata['sections']))

    return metadata


def get_text_preview(text, max_length=200):
    """Get a preview of the text, truncated to max_length characters."""
    if not text:
        return "Aucun contenu extrait"
    text = ' '.join(text.split())  # Normalize whitespace
    if len(text) <= max_length:
        return text
    return text[:max_length].rsplit(' ', 1)[0] + '…'


# ── Template Filters ──────────────────────────────────────────────────────────
@app.template_filter('preview')
def preview_filter(text, length=200):
    return get_text_preview(text, length)


@app.template_filter('from_json')
def from_json_filter(value):
    try:
        return json.loads(value) if value else {}
    except (json.JSONDecodeError, TypeError):
        return {}


@app.template_filter('format_date')
def format_date_filter(value):
    if not value:
        return ''
    try:
        dt = datetime.strptime(str(value), '%Y-%m-%d %H:%M:%S')
        return dt.strftime('%d/%m/%Y à %H:%M')
    except ValueError:
        return str(value)


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route('/')
def landing():
    """Landing page with hero section and call-to-action."""
    stats = get_stats()
    return render_template('index.html', stats=stats)


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login page for admin access."""
    if session.get('logged_in'):
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # Simple hardcoded credentials for demo/local use
        # In production, these should be in a database with hashed passwords
        if username == 'admin' and password == 'admin123':
            session['logged_in'] = True
            flash('Connexion réussie ! Bienvenue dans l\'espace administrateur.', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Identifiants invalides.', 'error')
            
    return render_template('login.html')


@app.route('/logout')
def logout():
    """Logout and clear session."""
    session.pop('logged_in', None)
    flash('Vous avez été déconnecté.', 'info')
    return redirect(url_for('landing'))


@app.route('/upload', methods=['GET', 'POST'])
def upload():
    """Handle CV upload via file or URL."""
    if request.method == 'POST':
        upload_type = request.form.get('upload_type', 'file')

        if upload_type == 'file':
            # File upload
            if 'cv_file' not in request.files:
                flash('Aucun fichier sélectionné.', 'error')
                return redirect(request.url)

            file = request.files['cv_file']
            if file.filename == '':
                flash('Aucun fichier sélectionné.', 'error')
                return redirect(request.url)

            if file and allowed_file(file.filename):
                original_filename = secure_filename(file.filename)
                
                # Check for duplicate
                existing_id = check_duplicate(original_filename)
                if existing_id:
                    flash(f'Ce CV ({original_filename}) existe déjà dans la base de données.', 'warning')
                    return redirect(url_for('view_cv', cv_id=existing_id))

                # Generate unique filename to avoid collisions
                ext = original_filename.rsplit('.', 1)[1].lower()
                unique_filename = f"{uuid.uuid4().hex}.{ext}"
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                file.save(filepath)

                # Extract text
                text = extract_text(filepath)
                if not text.strip():
                    flash('Impossible d\'extraire le texte du fichier. Le fichier est peut-être vide ou protégé.', 'warning')

                # Parse metadata
                metadata = parse_cv_metadata(text)

                # Insert into database
                cv_id = insert_cv(
                    filename=unique_filename,
                    original_filename=original_filename,
                    file_type='file',
                    text=text,
                    metadata=metadata
                )

                flash(f'CV "{original_filename}" importé avec succès !', 'success')
                return redirect(url_for('view_cv', cv_id=cv_id))
            else:
                flash('Format de fichier non supporté. Utilisez PDF, DOCX ou TXT.', 'error')
                return redirect(request.url)

        elif upload_type == 'url':
            # URL upload
            cv_url = request.form.get('cv_url', '').strip()
            if not cv_url:
                flash('Veuillez entrer une URL.', 'error')
                return redirect(request.url)

            try:
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
                response = requests.get(cv_url, timeout=10, stream=True, headers=headers)
                response.raise_for_status()
                
                content_type = response.headers.get('Content-Type', '').lower()
                if 'pdf' in content_type: ext = 'pdf'
                elif 'word' in content_type or 'officedocument' in content_type: ext = 'docx'
                else: ext = 'txt'
                
                # If extension not in URL, try to guess from content type
                if not any(cv_url.lower().endswith(e) for e in ALLOWED_EXTENSIONS):
                    unique_filename = f"{uuid.uuid4().hex}.{ext}"
                else:
                    original_name = cv_url.split('/')[-1] or "downloaded_cv"
                    unique_filename = f"{uuid.uuid4().hex}_{secure_filename(original_name)}"

                filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                
                with open(filepath, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                # Extract text
                text = extract_text(filepath)
                metadata = parse_cv_metadata(text)
                metadata['source_url'] = cv_url
                
                # Insert into database
                cv_id = insert_cv(
                    filename=unique_filename,
                    original_filename=cv_url.split('/')[-1] or cv_url,
                    file_type='url',
                    text=text,
                    url=cv_url,
                    metadata=metadata
                )
                
                flash('CV récupéré et analysé avec succès !', 'success')
                return redirect(url_for('view_cv', cv_id=cv_id))
                
            except Exception as e:
                flash(f"Erreur lors de la récupération de l'URL : {str(e)}", 'error')
                return redirect(request.url)

    return render_template('upload.html')


@app.route('/search')
@login_required
def search():
    """Search CVs with text or voice input."""
    query = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    results = []
    total = 0
    total_pages = 0

    if query:
        results, total, total_pages = search_cvs(query, page=page)

    return render_template(
        'search.html',
        query=query,
        results=results,
        total=total,
        page=page,
        total_pages=total_pages
    )


@app.route('/linkedin-search')
@login_required
def linkedin_search():
    """Search LinkedIn profiles by keywords."""
    return render_template('linkedin_search.html')


@app.route('/dashboard')
@login_required
def dashboard():
    """Display all CVs in a dashboard view."""
    page = request.args.get('page', 1, type=int)
    filter_type = request.args.get('type', '')
    cvs, total, total_pages = get_all_cvs(page=page, file_type=filter_type)
    stats = get_stats()

    return render_template(
        'dashboard.html',
        cvs=cvs,
        total=total,
        page=page,
        total_pages=total_pages,
        stats=stats,
        filter_type=filter_type
    )


@app.route('/cv/<int:cv_id>')
@login_required
def view_cv(cv_id):
    """View detailed information about a specific CV."""
    cv = get_cv_by_id(cv_id)
    if not cv:
        flash('CV non trouvé.', 'error')
        return redirect(url_for('dashboard'))
    return render_template('view_cv.html', cv=cv)


@app.route('/cv/<int:cv_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_cv(cv_id):
    """Edit CV metadata and text."""
    cv = get_cv_by_id(cv_id)
    if not cv:
        flash('CV non trouvé.', 'error')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        specialty = request.form.get('specialty', '').strip()
        experience = request.form.get('experience', '').strip()
        text = request.form.get('text', '').strip()
        emails = request.form.get('emails', '').split(',')
        phones = request.form.get('phones', '').split(',')
        skills = request.form.get('skills', '').split(',')
        
        # Clean up lists
        emails = [e.strip() for e in emails if e.strip()]
        phones = [p.strip() for p in phones if p.strip()]
        skills = [s.strip() for s in skills if s.strip()]
        
        metadata = json.loads(cv['metadata_json'])
        metadata['name'] = name
        metadata['specialty'] = specialty
        metadata['experience'] = experience
        metadata['emails'] = emails
        metadata['phones'] = phones
        metadata['skills'] = skills
        
        update_cv(cv_id, text, metadata)
        flash('CV mis à jour avec succès.', 'success')
        return redirect(url_for('view_cv', cv_id=cv_id))

    return render_template('edit_cv.html', cv=cv)


@app.route('/cv/<int:cv_id>/delete', methods=['POST'])
@login_required
def delete_cv_route(cv_id):
    """Delete a CV and its associated file."""
    cv = get_cv_by_id(cv_id)
    if cv:
        # Delete file if it exists
        if cv['file_type'] == 'file':
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], cv['filename'])
            if os.path.exists(filepath):
                os.remove(filepath)
        delete_cv(cv_id)
        flash('CV supprimé avec succès.', 'success')
    else:
        flash('CV non trouvé.', 'error')

    return redirect(url_for('dashboard'))


@app.route('/cv/<int:cv_id>/download')
@login_required
def download_cv(cv_id):
    """Download the original CV file."""
    cv = get_cv_by_id(cv_id)
    if cv and cv['file_type'] == 'file':
        return send_from_directory(
            app.config['UPLOAD_FOLDER'],
            cv['filename'],
            as_attachment=True,
            download_name=cv['original_filename']
        )
    flash('Fichier non disponible.', 'error')
    return redirect(url_for('dashboard'))


@app.route('/api/search')
@login_required
def api_search():
    """API endpoint for AJAX search."""
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'results': [], 'total': 0})

    results, total, _ = search_cvs(query, per_page=5)
    return jsonify({
        'results': [{
            'id': r['id'],
            'filename': r['original_filename'],
            'preview': get_text_preview(r['text'], 150),
            'created_at': r['created_at']
        } for r in results],
        'total': total
    })


# ── Error Handlers ─────────────────────────────────────────────────────────────
@app.errorhandler(404)
def not_found(e):
    return render_template('base.html', error_code=404, error_message='Page non trouvée'), 404


@app.errorhandler(413)
def too_large(e):
    flash('Le fichier est trop volumineux. Taille maximale : 16 Mo.', 'error')
    return redirect(url_for('upload'))


# ── Main ───────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)

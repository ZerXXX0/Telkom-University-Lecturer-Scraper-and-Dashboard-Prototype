import re

def normalize_name(name: str) -> str:
    if not name: return ""
    name = re.sub(r'[^a-zA-Z\s]', '', name)
    return ' '.join(name.split()).title()

def normalize_keyword(keyword: str) -> str:
    if not keyword: return ""
    return keyword.lower().strip()

def clean_name_for_search(name: str) -> str:
    if not name:
        return ""
    # Split by comma to remove degrees at the end
    base = name.split(',')[0].strip()
    
    # Suffixes to remove
    suffixes_to_remove = {
        's.kom', 's.kom.', 'skom', 'm.kom', 'm.kom.', 'mkom',
        's.t', 's.t.', 'st', 'm.t', 'm.t.', 'mt',
        's.si', 's.si.', 'ssi', 'm.stat', 'm.stat.', 'mstat',
        's.pd', 's.pd.', 'spd', 'm.pd', 'm.pd.', 'mpd',
        's.mat', 's.mat.', 'smat', 'm.mat', 'm.mat.', 'mmat',
        'm.sc', 'm.sc.', 'msc', 'b.sc', 'b.sc.', 'bsc',
        'm.eng', 'm.eng.', 'meng', 'ph.d', 'ph.d.', 'phd'
    }
    
    # Clean the end of the string word by word
    words = base.split()
    while words:
        last_word = words[-1].strip(',.').lower()
        if last_word in suffixes_to_remove:
            words.pop()
        else:
            break
            
    base = ' '.join(words)
    
    # Remove prefix titles case-insensitively
    lower_base = base.lower()
    prefixes = ['dr. eng.', 'dr. eng', 'dr.', 'prof. dr.', 'prof.', 'ir.', 'assoc. prof. dr.', 'assoc. prof.', 'assistant prof.']
    for prefix in prefixes:
        if lower_base.startswith(prefix):
            base = base[len(prefix):].strip()
            lower_base = lower_base[len(prefix):].strip()
    return base

def extract_keywords_from_pub_titles(titles: list) -> list:
    if not titles:
        return []
        
    stopwords = {
        # English stop words
        'a', 'about', 'above', 'after', 'again', 'against', 'all', 'am', 'an', 'and', 'any', 'are', 'arent', 'as', 'at',
        'be', 'because', 'been', 'before', 'being', 'below', 'between', 'both', 'but', 'by', 'cant', 'cannot', 'could',
        'couldnt', 'did', 'didnt', 'do', 'does', 'doesnt', 'doing', 'dont', 'down', 'during', 'each', 'few', 'for', 'from',
        'further', 'had', 'hadnt', 'has', 'hasnt', 'have', 'havent', 'having', 'he', 'hed', 'hell', 'hes', 'her', 'here',
        'heres', 'hers', 'herself', 'him', 'himself', 'his', 'how', 'hows', 'i', 'id', 'ill', 'im', 'ive', 'if', 'in',
        'into', 'is', 'isnt', 'it', 'its', 'itself', 'lets', 'me', 'more', 'most', 'mustnt', 'my', 'myself', 'no', 'nor',
        'not', 'of', 'off', 'on', 'once', 'only', 'or', 'other', 'ought', 'our', 'ours', 'ourselves', 'out', 'over', 'own',
        'same', 'shant', 'she', 'shed', 'shell', 'shes', 'should', 'shouldnt', 'so', 'some', 'such', 'than', 'that',
        'thats', 'the', 'their', 'theirs', 'them', 'themselves', 'then', 'there', 'theres', 'these', 'they', 'theyd',
        'theyll', 'theyre', 'theyve', 'this', 'those', 'through', 'to', 'too', 'under', 'until', 'up', 'very', 'was',
        'wasnt', 'we', 'wed', 'well', 'were', 'weve', 'werent', 'what', 'whats', 'when', 'whens', 'where', 'wheres',
        'which', 'while', 'who', 'whos', 'whom', 'why', 'whys', 'with', 'wont', 'would', 'wouldnt', 'you', 'youd',
        'youll', 'youre', 'youve', 'your', 'yours', 'yourself', 'yourselves',
        # Indonesian stop words
        'dan', 'yang', 'di', 'ke', 'dari', 'untuk', 'pada', 'dalam', 'dengan', 'adalah', 'yaitu', 'yakni', 'atau',
        'secara', 'terhadap', 'melalui', 'oleh', 'olehnya', 'untuk', 'bahwa', 'ini', 'itu', 'sebagai', 'pada', 'bagi',
        'serta', 'tentang', 'tersebut', 'bisa', 'dapat', 'akan', 'telah', 'sudah', 'sedang', 'menggunakan', 'berbasis',
        'metode', 'analisis', 'perancangan', 'sistem', 'aplikasi', 'model', 'studi', 'kasus', 'implementasi', 'pengaruh',
        'evaluasi', 'peningkatan', 'optimasi', 'perbandingan', 'klasifikasi', 'prediksi', 'berdasarkan', 'menggunakan',
        'rancang', 'bangun', 'pada', 'studi', 'kasus'
    }
    
    keywords = set()
    for title in titles:
        # Keep only letters, digits, spaces, and hyphens
        clean_title = re.sub(r'[^a-zA-Z0-9\s\-]', ' ', title)
        words = clean_title.split()
        for word in words:
            word_clean = word.lower().strip()
            # Filter out stop words, digits, and short words
            if len(word_clean) > 3 and word_clean not in stopwords and not word_clean.isdigit():
                keywords.add(word_clean)
    return sorted(list(keywords))

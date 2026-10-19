import os
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3

app = Flask(__name__)
app.secret_key = 'macave_secret_key_session'
DB_NAME = 'macave.db'

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    if not os.path.exists(DB_NAME):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE utilisateur (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE TABLE cave (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                utilisateur_id INTEGER UNIQUE NOT NULL,
                FOREIGN KEY(utilisateur_id) REFERENCES utilisateur(id)
            )
        ''')
        cursor.execute('''
            CREATE TABLE etagere (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nom TEXT NOT NULL,
                capacite INTEGER NOT NULL,
                cave_id INTEGER NOT NULL,
                FOREIGN KEY(cave_id) REFERENCES cave(id)
            )
        ''')
        cursor.execute('''
            CREATE TABLE vin_ref (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domaine TEXT NOT NULL,
                nom TEXT NOT NULL,
                type TEXT NOT NULL,
                millesime INTEGER NOT NULL,
                region TEXT NOT NULL,
                description TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE bouteille (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vin_id INTEGER NOT NULL,
                etagere_id INTEGER NOT NULL,
                prix_achat REAL NOT NULL,
                date_ajout TEXT NOT NULL,
                statut TEXT NOT NULL, -- 'stock' ou 'archive'
                FOREIGN KEY(vin_id) REFERENCES vin_ref(id),
                FOREIGN KEY(etagere_id) REFERENCES etagere(id)
            )
        ''')
        cursor.execute('''
            CREATE TABLE evaluation (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                note INTEGER NOT NULL,
                commentaire TEXT,
                auteur_id INTEGER NOT NULL,
                vin_id INTEGER NOT NULL,
                bouteille_id INTEGER UNIQUE NOT NULL,
                FOREIGN KEY(auteur_id) REFERENCES utilisateur(id),
                FOREIGN KEY(vin_id) REFERENCES vin_ref(id),
                FOREIGN KEY(bouteille_id) REFERENCES bouteille(id)
            )
        ''')
        conn.commit()
        conn.close()

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        email = request.form['email'].strip()
        password = request.form['password']
        
        if not username or not email or not password:
            flash("Tous les champs sont obligatoires.", "danger")
            return redirect(url_for('register'))
            
        hashed_pw = generate_password_hash(password)
        conn = get_db()
        try:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO utilisateur (username, email, password_hash) VALUES (?, ?, ?)",
                           (username, email, hashed_pw))
            user_id = cursor.lastrowid
            cursor.execute("INSERT INTO cave (utilisateur_id) VALUES (?)", (user_id,))
            conn.commit()
            flash("Compte créé avec succès. Veuillez vous connecter.", "success")
            return redirect(url_for('index'))
        except sqlite3.IntegrityError:
            flash("Nom d'utilisateur ou email déjà existant.", "danger")
        finally:
            conn.close()
    return render_template('register.html')

@app.route('/login', methods=['POST'])
def login():
    username = request.form['username'].strip()
    password = request.form['password']
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM utilisateur WHERE username = ?", (username,))
    user = cursor.fetchone()
    conn.close()
    
    if user and check_password_hash(user['password_hash'], password):
        session['user_id'] = user['id']
        session['username'] = user['username']
        return redirect(url_for('dashboard'))
    else:
        flash("Identifiants incorrects.", "danger")
        return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    
    user_id = session['user_id']
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM cave WHERE utilisateur_id = ?", (user_id,))
    cave = cursor.fetchone()
    cave_id = cave['id'] if cave else None
    
    etageres = []
    nb_bouteilles = 0
    nb_references = 0
    valeur_stock = 0.0
    capacite_totale = 0
    
    if cave_id:
        cursor.execute("""
            SELECT e.*, 
            (SELECT COUNT(*) FROM bouteille b WHERE b.etagere_id = e.id AND b.statut = 'stock') as occupation 
            FROM etagere e WHERE e.cave_id = ?
        """, (cave_id,))
        etageres = cursor.fetchall()
        
        for etag in etageres:
            capacite_totale += etag['capacite']
            
        cursor.execute("""
            SELECT COUNT(b.id) as nb, COUNT(DISTINCT b.vin_id) as refs, SUM(b.prix_achat) as total 
            FROM bouteille b JOIN etagere e ON b.etagere_id = e.id 
            WHERE e.cave_id = ? AND b.statut = 'stock'
        """, (cave_id,))
        res = cursor.fetchone()
        if res and res['nb']:
            nb_bouteilles = res['nb']
            nb_references = res['refs']
            valeur_stock = res['total'] if res['total'] else 0.0

    occupation_globale = (nb_bouteilles / capacite_totale * 100) if capacite_totale > 0 else 0
    
    conn.close()
    return render_template('dashboard.html', 
                           etageres=etageres, 
                           nb_bouteilles=nb_bouteilles,
                           nb_references=nb_references,
                           valeur_stock=valeur_stock,
                           capacite_totale=capacite_totale,
                           occupation_globale=round(occupation_globale, 1))

@app.route('/etagere/add', methods=['POST'])
def add_etagere():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    
    nom = request.form['nom'].strip()
    capacite = int(request.form['capacite'])
    
    if capacite <= 0 or not nom:
        flash("La capacité doit être strictement positive et le nom requis.", "danger")
        return redirect(url_for('dashboard'))
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM cave WHERE utilisateur_id = ?", (session['user_id'],))
    cave_id = cursor.fetchone()['id']
    
    # Vérification unicité du nom de l'étagère dans la cave
    cursor.execute("SELECT id FROM etagere WHERE cave_id = ? AND nom = ?", (cave_id, nom))
    if cursor.fetchone():
        flash("Une étagère avec ce nom existe déjà dans votre cave.", "danger")
        conn.close()
        return redirect(url_for('dashboard'))
        
    cursor.execute("INSERT INTO etagere (nom, capacite, cave_id) VALUES (?, ?, ?)", (nom, capacite, cave_id))
    conn.commit()
    conn.close()
    flash("Étagère ajoutée avec succès.", "success")
    return redirect(url_for('dashboard'))

@app.route('/etagere/delete/<int:etagere_id>', methods=['POST'])
def delete_etagere(etagere_id):
    if 'user_id' not in session:
        return redirect(url_for('index'))
        
    conn = get_db()
    cursor = conn.cursor()
    # Vérification si l'étagère contient des bouteilles en stock
    cursor.execute("SELECT COUNT(*) as nb FROM bouteille WHERE etagere_id = ? AND statut = 'stock'", (etagere_id,))
    if cursor.fetchone()['nb'] > 0:
        flash("Impossible de supprimer une étagère non vide.", "danger")
    else:
        cursor.execute("DELETE FROM etagere WHERE id = ?", (etagere_id,))
        conn.commit()
        flash("Étagère supprimée.", "success")
    conn.close()
    return redirect(url_for('dashboard'))

@app.route('/catalog')
def catalog():
    if 'user_id' not in session:
        return redirect(url_for('index'))
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vin_ref")
    vins = cursor.fetchall()
    
    # Récupérer les étagères de l'utilisateur pour le formulaire d'ajout
    cursor.execute("SELECT id FROM cave WHERE utilisateur_id = ?", (session['user_id'],))
    cave = cursor.fetchone()
    etageres = []
    if cave:
        cursor.execute("SELECT * FROM etagere WHERE cave_id = ?", (cave['id'],))
        etageres = cursor.fetchall()
        
    conn.close()
    return render_template('catalog.html', vins=vins, etageres=etageres)

@app.route('/vin/add', methods=['POST'])
def add_vin_and_bouteilles():
    if 'user_id' not in session:
        return redirect(url_for('index'))
        
    domaine = request.form['domaine'].strip()
    nom = request.form['nom'].strip()
    type_vin = request.form['type']
    millesime = int(request.form['millesime'])
    region = request.form['region'].strip()
    description = request.form['description'].strip()
    
    etagere_id = int(request.form['etagere_id'])
    quantite = int(request.form['quantite'])
    prix_achat = float(request.form['prix_achat'])
    
    if quantite <= 0 or prix_achat < 0:
        flash("Quantité et prix invalides.", "danger")
        return redirect(url_for('catalog'))
        
    conn = get_db()
    cursor = conn.cursor()
    
    # Vérification de la capacité de l'étagère de destination
    cursor.execute("""
        SELECT capacite, (SELECT COUNT(*) FROM bouteille WHERE etagere_id = ? AND statut = 'stock') as occup 
        FROM etagere WHERE id = ?
    """, (etagere_id, etagere_id))
    etot = cursor.fetchone()
    if not etot or (etot['occup'] + quantite > etot['capacite']):
        flash("Capacité de l'étagère insuffisante pour cet ajout !", "danger")
        conn.close()
        return redirect(url_for('catalog'))
        
    # Vérification ou création de la référence (unicité par domaine, nom, type, millesime, region)
    cursor.execute("""
        SELECT id FROM vin_ref WHERE domaine = ? AND nom = ? AND type = ? AND millesime = ? AND region = ?
    """, (domaine, nom, type_vin, millesime, region))
    vin = cursor.fetchone()
    
    if vin:
        vin_id = vin['id']
    else:
        cursor.execute("""
            INSERT INTO vin_ref (domaine, nom, type, millesime, region, description) 
            VALUES (?, ?, ?, ?, ?, ?)
        """, (domaine, nom, type_vin, millesime, region, description))
        vin_id = cursor.lastrowid
        
    # Ajout atomique des bouteilles
    import datetime
    date_auj = datetime.date.today().isoformat()
    for _ in range(quantite):
        cursor.execute("""
            INSERT INTO bouteille (vin_id, etagere_id, prix_achat, date_ajout, statut) 
            VALUES (?, ?, ?, ?, 'stock')
        """, (vin_id, etagere_id, prix_achat, date_auj))
        
    conn.commit()
    conn.close()
    flash(f"{quantite} bouteille(s) ajoutée(s) avec succès.", "success")
    return redirect(url_for('catalog'))

@app.route('/stock')
def stock():
    if 'user_id' not in session:
        return redirect(url_for('index'))
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM cave WHERE utilisateur_id = ?", (session['user_id'],))
    cave = cursor.fetchone()
    
    bouteilles = []
    etageres = []
    if cave:
        cursor.execute("SELECT * FROM etagere WHERE cave_id = ?", (cave['id'],))
        etageres = cursor.fetchall()
        
        cursor.execute("""
            SELECT b.id, v.domaine, v.nom, v.type, v.millesime, v.region, b.prix_achat, b.date_ajout, e.nom as etagere_nom, e.id as etagere_id
            FROM bouteille b 
            JOIN vin_ref v ON b.vin_id = v.id 
            JOIN etagere e ON b.etagere_id = e.id 
            WHERE e.cave_id = ? AND b.statut = 'stock'
        """, (cave['id'],))
        bouteilles = cursor.fetchall()
        
    conn.close()
    return render_template('stock.html', bouteilles=bouteilles, etageres=etageres)

@app.route('/bouteille/deplacer/<int:bouteille_id>', methods=['POST'])
def deplacer_bouteille(bouteille_id):
    if 'user_id' not in session:
        return redirect(url_for('index'))
        
    nouvelle_etagere_id = int(request.form['nouvelle_etagere_id'])
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Vérification capacité étagère cible
    cursor.execute("""
        SELECT capacite, (SELECT COUNT(*) FROM bouteille WHERE etagere_id = ? AND statut = 'stock') as occup 
        FROM etagere WHERE id = ?
    """, (nouvelle_etagere_id, nouvelle_etagere_id))
    etot = cursor.fetchone()
    
    if not etot or (etot['occup'] + 1 > etot['capacite']):
        flash("Déplacement refusé : capacité de l'étagère de destination atteinte.", "danger")
    else:
        cursor.execute("UPDATE bouteille SET etagere_id = ? WHERE id = ?", (nouvelle_etagere_id, bouteille_id))
        conn.commit()
        flash("Bouteille déplacée avec succès.", "success")
        
    conn.close()
    return redirect(url_for('stock'))

@app.route('/bouteille/retirer/<int:bouteille_id>', methods=['POST'])
def retirer_bouteille(bouteille_id):
    if 'user_id' not in session:
        return redirect(url_for('index'))
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM bouteille WHERE id = ? AND statut = 'stock'", (bouteille_id,))
    conn.commit()
    conn.close()
    flash("Bouteille retirée définitivement de l'inventaire.", "success")
    return redirect(url_for('stock'))

@app.route('/bouteille/archiver/<int:bouteille_id>', methods=['POST'])
def archiver_bouteille(bouteille_id):
    if 'user_id' not in session:
        return redirect(url_for('index'))
        
    note = int(request.form['note'])
    commentaire = request.form['commentaire'].strip()
    
    if not (0 <= note <= 20):
        flash("La note doit être comprise entre 0 et 20.", "danger")
        return redirect(url_for('stock'))
        
    conn = get_db()
    cursor = conn.cursor()
    
    # Vérifier que la bouteille est en stock et appartient à l'utilisateur
    cursor.execute("""
        SELECT b.vin_id FROM bouteille b 
        JOIN etagere e ON b.etagere_id = e.id 
        JOIN cave c ON e.cave_id = c.id 
        WHERE b.id = ? AND c.utilisateur_id = ? AND b.statut = 'stock'
    """, (bouteille_id, session['user_id']))
    b = cursor.fetchone()
    
    if not b:
        flash("Action non autorisée ou bouteille déjà archivée.", "danger")
    else:
        vin_id = b['vin_id']
        cursor.execute("UPDATE bouteille SET statut = 'archive' WHERE id = ?", (bouteille_id,))
        cursor.execute("""
            INSERT INTO evaluation (note, commentaire, auteur_id, vin_id, bouteille_id) 
            VALUES (?, ?, ?, ?, ?)
        """, (note, commentaire, session['user_id'], vin_id, bouteille_id))
        conn.commit()
        flash("Bouteille archivée et évaluation enregistrée avec succès.", "success")
        
    conn.close()
    return redirect(url_for('stock'))

@app.route('/historique')
def historique():
    if 'user_id' not in session:
        return redirect(url_for('index'))
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT b.id, v.domaine, v.nom, v.millesime, ev.note, ev.commentaire, ev.id as eval_id
        FROM bouteille b
        JOIN vin_ref v ON b.vin_id = v.id
        JOIN evaluation ev ON ev.bouteille_id = b.id
        JOIN etagere e ON b.etagere_id = e.id
        WHERE e.cave_id = (SELECT id FROM cave WHERE utilisateur_id = ?) AND b.statut = 'archive'
    """, (session['user_id'],))
    archives = cursor.fetchall()
    conn.close()
    return render_template('historique.html', archives=archives)

@app.route('/communaute')
def communaute():
    if 'user_id' not in session:
        return redirect(url_for('index'))
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT v.*, 
        (SELECT AVG(ev.note) FROM evaluation ev WHERE ev.vin_id = v.id) as moyenne,
        (SELECT COUNT(ev.id) FROM evaluation ev WHERE ev.vin_id = v.id) as nb_evas
        FROM vin_ref v
    """)
    vins = cursor.fetchall()
    
    evaluations_dict = {}
    for vin in vins:
        cursor.execute("""
            SELECT ev.*, u.username FROM evaluation ev 
            JOIN utilisateur u ON ev.auteur_id = u.id 
            WHERE ev.vin_id = ?
        """, (vin['id'],))
        evaluations_dict[vin['id']] = cursor.fetchall()
        
    conn.close()
    return render_template('communaute.html', vins=vins, evaluations_dict=evaluations_dict)

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)
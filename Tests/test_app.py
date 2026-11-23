import sys
import os
import pytest

# Ajoute le dossier parent (racine du projet) au chemin Python pour trouver app.py
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import app as main_app


@pytest.fixture
def client(tmp_path):
    """
    Fixture Pytest : Prépare une base de données temporaire isolée avant chaque test.
    """
    db_file = tmp_path / "test_macave.db"
    main_app.DB_NAME = str(db_file)
    main_app.app.config['TESTING'] = True
    main_app.init_db()
    
    with main_app.app.test_client() as client:
        yield client



# SCÉNARIO 1 : Créer un compte -> Connexion possible et cave privée accessible

def test_creation_compte_et_connexion(client):
    # 1. Inscription
    reponse_reg = client.post('/register', data={
        'username': 'alice',
        'email': 'alice@exemple.fr',
        'password': 'SecretPassword123'
    }, follow_redirects=True)
    
    html_reg = reponse_reg.get_data(as_text=True)
    assert reponse_reg.status_code == 200
    assert "Compte créé avec succès" in html_reg

    # 2. Connexion
    reponse_login = client.post('/login', data={
        'username': 'alice',
        'password': 'SecretPassword123'
    }, follow_redirects=True)
    
    assert reponse_login.status_code == 200
    
    # 3. Vérification session et cave en BDD
    with client.session_transaction() as sess:
        assert 'user_id' in sess
        user_id = sess['user_id']
        
    conn = main_app.get_db()
    cave = conn.execute("SELECT * FROM cave WHERE utilisateur_id = ?", (user_id,)).fetchone()
    conn.close()
    
    assert cave is not None



# SCÉNARIO 2 : Créer une étagère de capacité 10 -> Occupation initiale de 0/10

def test_creation_etagere_capacite_10(client):
    client.post('/register', data={'username': 'bob', 'email': 'bob@test.fr', 'password': '123'})
    client.post('/login', data={'username': 'bob', 'password': '123'})

    reponse = client.post('/etagere/add', data={
        'nom': 'Étagère Bordeaux',
        'capacite': '10'
    }, follow_redirects=True)

    assert reponse.status_code == 200

    conn = main_app.get_db()
    etagere = conn.execute("SELECT * FROM etagere WHERE nom = 'Étagère Bordeaux'").fetchone()
    occupation = conn.execute(
        "SELECT COUNT(*) as nb FROM bouteille WHERE etagere_id = ? AND statut = 'stock'", 
        (etagere['id'],)
    ).fetchone()['nb']
    conn.close()

    assert etagere is not None
    assert etagere['capacite'] == 10
    assert occupation == 0



# SCÉNARIO 3 : Ajouter 5 bouteilles identiques -> 5 exemplaires, 1 seule référence

def test_ajout_5_bouteilles_identiques(client):
    client.post('/register', data={'username': 'claire', 'email': 'claire@test.fr', 'password': '123'})
    client.post('/login', data={'username': 'claire', 'password': '123'})
    client.post('/etagere/add', data={'nom': 'Casier A', 'capacite': '10'})

    reponse = client.post('/vin/add', data={
        'domaine': 'Château Margaux',
        'nom': 'Pavillon Rouge',
        'type': 'Rouge',
        'millesime': '2018',
        'region': 'Bordeaux',
        'description': 'Grand cru classé',
        'etagere_id': '1',
        'quantite': '5',
        'prix_achat': '180.0'
    }, follow_redirects=True)

    assert reponse.status_code == 200

    conn = main_app.get_db()
    nb_refs = conn.execute("SELECT COUNT(*) as nb FROM vin_ref").fetchone()['nb']
    nb_bouteilles = conn.execute("SELECT COUNT(*) as nb FROM bouteille WHERE statut = 'stock'").fetchone()['nb']
    conn.close()

    assert nb_refs == 1
    assert nb_bouteilles == 5



# SCÉNARIO 4 : Ajouter 6 bouteilles sur étagère à 5/10 -> Refus sans ajout partiel

def test_refus_depassement_capacite_sans_ajout_partiel(client):
    client.post('/register', data={'username': 'david', 'email': 'david@test.fr', 'password': '123'})
    client.post('/login', data={'username': 'david', 'password': '123'})
    client.post('/etagere/add', data={'nom': 'Casier B', 'capacite': '10'})
    
    donnees_vin = {
        'domaine': 'Domaine de la Romanée',
        'nom': 'Cuvée Prestige',
        'type': 'Rouge',
        'millesime': '2020',
        'region': 'Bourgogne',
        'description': '',
        'etagere_id': '1',
        'quantite': '5',
        'prix_achat': '95.0'
    }
    client.post('/vin/add', data=donnees_vin)

    # Tentative d'ajout de 6 bouteilles supplémentaires (5 + 6 = 11 > 10)
    donnees_vin['quantite'] = '6'
    reponse = client.post('/vin/add', data=donnees_vin, follow_redirects=True)

    html_rep = reponse.get_data(as_text=True)
    assert "Capacité de l&#39;étagère insuffisante" in html_rep or "Capacité de l'étagère insuffisante" in html_rep
    
    conn = main_app.get_db()
    nb_bouteilles = conn.execute("SELECT COUNT(*) as nb FROM bouteille WHERE statut = 'stock'").fetchone()['nb']
    conn.close()

    assert nb_bouteilles == 5



# SCÉNARIO 5 : Supprimer une étagère non vide -> Refus et message explicite

def test_refus_suppression_etagere_non_vide(client):
    client.post('/register', data={'username': 'emma', 'email': 'emma@test.fr', 'password': '123'})
    client.post('/login', data={'username': 'emma', 'password': '123'})
    client.post('/etagere/add', data={'nom': 'Étagère Pleine', 'capacite': '5'})
    client.post('/vin/add', data={
        'domaine': 'Guigal',
        'nom': 'La Mouline',
        'type': 'Rouge',
        'millesime': '2015',
        'region': 'Rhône',
        'description': '',
        'etagere_id': '1',
        'quantite': '1',
        'prix_achat': '250.0'
    })

    reponse = client.post('/etagere/delete/1', follow_redirects=True)

    html_rep = reponse.get_data(as_text=True)
    assert "Impossible de supprimer une étagère non vide" in html_rep
    
    conn = main_app.get_db()
    etagere = conn.execute("SELECT * FROM etagere WHERE id = 1").fetchone()
    conn.close()

    assert etagere is not None
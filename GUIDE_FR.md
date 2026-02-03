# 🛡️ SentinelDesk — Guide de Démarrage Rapide

## Installation (Windows)

### 1. Prérequis
- **Python 3.10+** ([télécharger ici](https://www.python.org/downloads/))
  - ⚠️ Cocher "Add Python to PATH" pendant l'installation

### 2. Installation des dépendances
```bash
cd sentineldesk_v2
pip install -r requirements.txt
```

Ou manuellement :
```bash
pip install PySide6 psutil
```

### 3. Lancement

**Option A — Script Windows :**
Double-cliquez sur `run.bat`

**Option B — Ligne de commande :**
```bash
python -m sentineldesk
```

---

## 🎯 Comprendre l'Interface

### Onglet "Dashboard"
- **Gauche :** Top 50 processus par CPU
- **Droite :** Connexions TCP actives
- **Haut :** Cartes métriques (CPU, RAM, Réseau) avec graphiques animés
- **💡 Astuce :** Cliquez sur n'importe quel en-tête de colonne pour trier

### Onglet "Process Tree" 🆕
- **Arbre hiérarchique** montrant qui a lancé quoi
- **Processus suspects en rouge** :
  - `cmd.exe` ou `powershell.exe` lancé par Word/Excel
  - Exe lancé depuis `%TEMP%`, `%APPDATA%` ou Downloads
  - `rundll32.exe` avec parent suspect
- **💡 Astuce :** Dérouler un processus pour voir ses enfants

### Onglet "Alerts"
- Toutes les alertes de sécurité avec badges de sévérité
- **Bouton "Approve & Trust Exe"** : marquer un exe comme sûr (ne plus alerter)

### Onglet "Persistence" 🆕
- **Run Keys** : Clés de registre qui lancent des programmes au démarrage
- **Startup** : Fichiers dans le dossier Démarrage
- **Tasks** : Tâches planifiées
- **Nouveaux éléments** en rouge jusqu'à ce que vous cliquiez "Acknowledge Entry"

### Onglet "Timeline"
- Historique complet de tous les événements
- Searchable et filtrable

---

## 🔧 Configuration

Éditez `~/.sentineldesk/config.json` :

```json
{
  "sample_interval_ms": 1000,              // Fréquence d'échantillonnage (ms)
  
  "suspicious_parent_alert": true,         // Activer détection parent-child process
  "persistence_watch_enabled": true,       // Surveiller Run keys / Startup
  
  "cpu_spike_threshold_pct": 85.0,         // Seuil CPU pour alerte
  "cpu_spike_sustain_seconds": 15,         // Durée minimale du pic
  
  "blacklist_path": ""                     // Chemin custom (ou "" pour défaut)
}
```

---

## 🛡️ Fonctions de Sécurité Expliquées

### 1. Détection de Parentage Suspect

**Que fait-elle ?**  
Détecte quand un processus dangereux est lancé par un parent inattendu.

**Exemples concrets :**
- Vous ouvrez un document Word malveillant
- La macro lance `powershell.exe` en arrière-plan
- **SentinelDesk alerte** : "Shell spawned by Office: powershell.exe ← WINWORD.EXE"

**Pourquoi c'est important :**  
C'est la méthode **#1** utilisée par les ransomwares et trojans pour infecter via email.

---

### 2. Hash Blacklist

**Que fait-elle ?**  
Compare les hash SHA-256 des exe en cours d'exécution contre une liste de malware connus.

**Comment l'utiliser :**
1. Créer/éditer `~/.sentineldesk/blacklist_sha256.txt`
2. Une ligne = un hash (64 caractères hex)
3. Mise à jour automatique sans redémarrer

**Où trouver des hash de malware :**
- [VirusTotal](https://www.virustotal.com/) — chercher un fichier suspect
- [Malware Bazaar](https://bazaar.abuse.ch/) — base de données publique
- [MITRE ATT&CK](https://attack.mitre.org/) — tactiques et techniques

**Exemple :**
```
# Dans blacklist_sha256.txt
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
```

---

### 3. Surveillance de Persistance

**Que fait-elle ?**  
Surveille les 3 mécanismes principaux que les malware utilisent pour se réinstaller automatiquement au démarrage :

1. **Registry Run Keys**  
   `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`

2. **Startup Folder**  
   `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`

3. **Scheduled Tasks**  
   Tâches planifiées Windows

**Quand alerter ?**  
Quand une **nouvelle entrée** apparaît que vous n'avez pas créée vous-même.

**Exemple réel :**  
Un malware ajoute cette clé :
```
HKCU\...\Run\GoogleUpdate = "C:\Users\...\AppData\malware.exe"
```
→ **SentinelDesk alerte** dans les 1 seconde

---

### 4. Intégrité des Fichiers

**Que fait-elle ?**  
Calcule le SHA-256 de chaque exe **la première fois qu'il tourne**, puis alerte si le fichier est **modifié pendant qu'il tourne** (très rare mais critique).

**Cas d'usage :**  
Un rootkit modifie `svchost.exe` en mémoire pour injecter du code.

---

### 5. CPU Spike Detection

**Que fait-elle ?**  
Alerte si un processus utilise >85% CPU pendant >15 secondes.

**Pourquoi ?**  
Les cryptominers cachés monopolisent le CPU.

---

## 🧪 Tester les Alertes

### Test 1 : Parentage (sans danger)

1. Ouvrir Word
2. Alt+F11 → Éditeur VBA
3. Insérer ce code :
   ```vbnet
   Sub TestMacro()
       Shell "cmd.exe /c echo test > %TEMP%\test.txt", vbHide
   End Sub
   ```
4. Lancer la macro
5. **Résultat :** Alerte rouge "SUSPICIOUS_PARENTAGE_OFFICE" + processus `cmd.exe` rouge dans l'arbre

### Test 2 : Blacklist (sans danger)

1. Obtenir le hash de notepad :
   ```bash
   certutil -hashfile C:\Windows\notepad.exe SHA256
   ```
2. Copier le hash dans `~/.sentineldesk/blacklist_sha256.txt`
3. Lancer `notepad.exe`
4. **Résultat :** Alerte rouge "BLACKLISTED_HASH"

### Test 3 : Persistence (sans danger)

```bash
reg add HKCU\Software\Microsoft\Windows\CurrentVersion\Run /v TestEntry /d "C:\fake.exe"
```
**Résultat :** Alerte rouge "NEW_PERSISTENCE" dans l'onglet Alerts + ligne rouge dans l'onglet Persistence

**Nettoyer après :**
```bash
reg delete HKCU\Software\Microsoft\Windows\CurrentVersion\Run /v TestEntry /f
```

---

## ❓ FAQ

### Q : Pourquoi tant d'alertes au premier lancement ?
**R :** Au premier lancement, **tous** les processus sont nouveaux. SentinelDesk construit une baseline pendant 5-10 minutes. Après, seuls les **vrais changements** génèrent des alertes.

### Q : Mon antivirus détecte SentinelDesk comme suspect
**R :** C'est normal — SentinelDesk lit les processus et le registre (comportement typique d'un outil de sécurité). Ajoutez-le aux exclusions.

### Q : Comment mettre à jour la blacklist automatiquement ?
**R :** Actuellement manuel. Sprint B ajoutera le téléchargement automatique depuis une URL.

### Q : Puis-je exporter les alertes ?
**R :** Actuellement via SQLite :
```bash
sqlite3 ~/.sentineldesk/sentineldesk.db
.mode csv
.output alerts.csv
SELECT * FROM alerts;
.quit
```
Sprint C ajoutera export CSV/JSON/HTML intégré.

### Q : Ça marche sur Linux/Mac ?
**R :** Pas encore. Le monitoring processus/réseau fonctionne, mais la détection de persistance est Windows-only pour l'instant. Support Linux/Mac prévu Sprint B.

---

## 🔐 Sécurité & Confidentialité

- **100% local** — Aucune donnée envoyée sur internet
- **Aucun télémétrie** — Pas de tracking, pas de "phone home"
- **Base de données locale** — Tout est dans `~/.sentineldesk/sentineldesk.db`
- **Open source** — Vous pouvez auditer tout le code

---

## 📞 Support

**Problème ?**  
1. Vérifier les logs dans la console
2. Vérifier `~/.sentineldesk/config.json` est valide
3. Essayer de supprimer `~/.sentineldesk/sentineldesk.db` (reset complet)

**Feature request ?**  
Ouvrir une issue sur GitHub (si publié)

---

## 🎓 Pour Aller Plus Loin

### Apprendre la détection d'attaque
- [MITRE ATT&CK Navigator](https://mitre-attack.github.io/attack-navigator/)
- [Any.run — Sandbox interactif](https://app.any.run/)
- [Hybrid Analysis](https://www.hybrid-analysis.com/)

### Flux de threat intelligence
- [AlienVault OTX](https://otx.alienvault.com/)
- [Abuse.ch](https://abuse.ch/)
- [VirusShare](https://virusshare.com/)

---

**Restez vigilant. Restez protégé. 🛡️**

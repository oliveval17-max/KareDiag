# Paquet Debian KareDiag

## Construire

Sur toute distribution Debian/Ubuntu/Mint/Kaisen (aucun outil spécifique :

```bash
./deb/construire_deb.sh
```

Le script :

1. lit la version dans `karediag.py` (`VERSION_APPLICATION`) ;
2. génère les icônes PNG (128/64/48) — moteur Qt hors-écran si PyQt5 est
   disponible, sinon rendu **pur Python** sans aucune dépendance ;
3. assemble `karediag_<version>_all.deb` (wrapper `/usr/bin/karediag`,
   application, lanceur de menu, icônes hicolor, documentation).

## Installer / désinstaller

```bash
sudo apt install ./karediag_8.4.0_all.deb
sudo apt remove karediag
```

Après installation, « KareDiag » apparaît dans le menu Applications avec
son icône ; `karediag` est également disponible en ligne de commande.

## Contenu installé

| Fichier | Rôle |
|---|---|
| `/usr/bin/karediag` | Commande de lancement |
| `/usr/share/karediag/karediag.py` | Application (fichier unique) |
| `/usr/share/applications/karediag.desktop` | Entrée de menu système |
| `/usr/share/icons/hicolor/*/apps/karediag.png` | Icônes 128/64/48 |
| `/usr/share/doc/karediag/` | README et copyright |

> ℹ️ Si l'utilisateur lance déjà `karediag.py` en fichier volant,
> l'installation automatique du lanceur utilisateur
> (`~/.local/share/applications/karediag.desktop`, même identifiant)
> reste prioritaire sur celle du paquet : aucun doublon de menu.

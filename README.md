# DATA MEGA V2

Bot Telegram de vente de produits numériques, 100 % administrable depuis
Telegram : catégories/produits dynamiques, stock unitaire, portefeuille
interne, dépôts crypto via NOWPayments, livraison automatique.

## Stack

Python · Aiogram 3 · SQLAlchemy 2.0 (async) · SQLite (ou PostgreSQL) ·
Aiohttp · NOWPayments · Railway

## Architecture

```
main.py                 # point d'entrée (polling + serveur web)
config.py                # variables d'environnement
db/
  models.py               # tables SQLAlchemy
  session.py               # moteur + init_db (création des tables)
  seed.py                   # amorce le catalogue initial (Fiches / Carte)
services/
  wallet.py                # crédit / débit portefeuille
  stock.py                  # réservation atomique (anti double-vente)
  delivery.py                # livraison automatique + remboursement si échec
  nowpayments.py              # création paiement + QR + vérif signature IPN
  journal.py                   # journal des actions admin
  notify.py                     # notifications admin
keyboards/               # claviers inline (client / admin)
handlers/
  user/                   # /start, boutique, portefeuille, compte, support
  admin/                   # /admin — dashboard, produits, catégories, stock,
                            # clients, portefeuille, commandes, statistiques,
                            # notifications, journal, paramètres
webhook/server.py        # /health + /ipn/nowpayments (idempotent)
```

## Fonctionnement clé

- **Catégories et produits** : entièrement stockés en base, jamais codés
  en dur. Tout se crée/modifie/désactive depuis `/admin` dans Telegram.
- **Stock unitaire** : chaque fichier envoyé par l'admin (via "Restock")
  devient une unité (`available` → `reserved` → `sold`). La réservation
  utilise une requête `UPDATE ... WHERE id = (SELECT ... LIMIT 1)`
  atomique : impossible que deux clients réservent la même unité.
- **Montants en centimes** : tous les montants USD (`Wallet.balance_cents`,
  `Product.price_cents`, `Order.price_cents`, `Deposit.amount_usd_cents`,
  `WalletTransaction.amount_cents`) sont stockés en entier (centimes), pas
  en float — voir `utils/money.py` pour les seules fonctions de conversion
  à utiliser (saisie utilisateur → centimes, centimes → affichage). Un
  entier est représenté exactement sur SQLite comme sur PostgreSQL, alors
  qu'un float accumule des erreurs d'arrondi sur des soldes.
- **Portefeuille** : `wallets` + `wallet_transactions` (types : deposit,
  purchase, refund, bonus, admin_credit, admin_debit). Chaque mouvement
  est journalisé. `credit()`/`debit()` (`services/wallet.py`) utilisent un
  `UPDATE` conditionnel atomique (jamais de lire-puis-écrire) : deux
  opérations concurrentes sur le même utilisateur ne peuvent jamais
  produire un solde incohérent ou négatif, y compris sous PostgreSQL avec
  plusieurs connexions simultanées.
- **Dépôts crypto** : le client choisit un montant + une crypto sans
  quitter Telegram. Le bot appelle l'API NOWPayments, affiche adresse +
  montant + QR code dans le chat. Le webhook `/ipn/nowpayments` crédite
  le solde automatiquement (signature HMAC-SHA512 vérifiée). L'anti
  double-crédit se fait par une "réclamation" atomique (`UPDATE ... WHERE
  credited=False`) plutôt qu'un simple test en Python : même si NOWPayments
  envoie deux notifications quasi simultanées pour le même paiement, une
  seule peut créditer le solde.
- **Achat avec solde** : réservation de stock → débit du portefeuille →
  livraison automatique (envoi du fichier Telegram) → unité marquée
  `sold`. En cas d'échec de livraison, remboursement automatique et
  notification admin.
- **Rupture de stock** : le produit affiche "en rupture" et le bouton
  d'achat est désactivé.
- **Réservations orphelines** : si le bot crashe entre la réservation
  d'une unité de stock et la fin de l'achat, une tâche de fond
  (`services/background_tasks.py`, même boucle que le filet de secours
  dépôts) libère automatiquement ce qui est resté bloqué plus de
  `STALE_RESERVATION_TIMEOUT_MINUTES` (15 min par défaut).
- **Brouillons / Corbeille** : un produit `draft` n'est pas visible côté
  client. La suppression est logique (`deleted`), restaurable depuis la
  corbeille.

## Réglages modifiables depuis Telegram

Depuis le panel admin (⚙️ Paramètres), certaines valeurs sont modifiables
directement en écrivant un message, sans toucher aux variables
d'environnement Railway ni redéployer :

- Nom d'utilisateur du support
- Dépôt minimum (USD)
- Seuil de stock faible
- Montants de dépôt proposés (boutons rapides)

Ces réglages sont stockés dans la table `settings` (voir
`services/settings.py`) et prennent le pas sur la valeur par défaut de
`config.py`/l'environnement dès qu'un admin les modifie.

**Volontairement absents de ce panel**, car ce sont des secrets ou des
paramètres d'infrastructure critiques : `BOT_TOKEN`, `ADMIN_IDS`,
`DATABASE_URL`, les clés NOWPayments. Les rendre modifiables depuis un
chat Telegram (visible dans l'historique, capturable par capture d'écran)
ou par n'importe quel admin serait risqué — `ADMIN_IDS` en particulier
pourrait servir à s'auto-accorder un accès permanent ou à verrouiller les
autres admins. Ils restent définis uniquement via les variables
d'environnement Railway.

## Renommer les boutons du bot

Depuis 🏷 Libellés (menu admin), **tous les boutons du bot** (client et
admin, ~54 libellés) sont renommables individuellement, organisés par
section (Menu client, Boutique, Portefeuille, Menu admin, Produits admin,
etc.). Chaque libellé peut être réinitialisé à sa valeur par défaut.

Techniquement : une middleware (`middlewares.py`) charge le dict complet
des libellés en une seule requête à chaque update Telegram, et l'injecte
automatiquement dans tous les handlers et filtres qui déclarent un
paramètre `labels: dict[str, str]`. Les boutons du clavier persistant
(menu du bas : Boutique, Mon Solde...) utilisent un filtre dédié
(`utils/filters.py::MatchesLabel`) qui compare le texte reçu au libellé
*actuel* plutôt qu'à un texte figé — renommer un bouton ne casse donc
jamais le handler correspondant.

## Recherche produit

Depuis 📦 Produits → 🔎 Rechercher, retrouvez un produit par son numéro de
référence (`#12` ou `12`) ou par une partie de son titre.



Le projet utilise désormais Alembic pour toute évolution future du schéma
de base de données (`init_db()`/`create_all` reste utilisé uniquement pour
créer les tables manquantes au premier démarrage, jamais pour les faire
évoluer).

**Première mise en place** (à faire une seule fois, sur une base déjà
créée par `init_db()` — neuve ou existante) :

```bash
pip install -r requirements.txt
alembic stamp head
```

`stamp head` ne modifie aucune donnée ni structure : il marque juste la
base comme étant au niveau de la migration `0001_baseline` (qui ne fait
rien), point de départ pour toutes les migrations futures.

**Pour toute évolution de schéma ultérieure** (nouvelle colonne, nouvelle
table, etc.) :

```bash
# 1. Modifier db/models.py
# 2. Générer la migration (compare les modèles à la base réelle)
alembic revision --autogenerate -m "description du changement"
# 3. RELIRE le fichier généré dans alembic/versions/ avant de l'appliquer —
#    l'autogénération ne détecte pas tout (renommages, contraintes
#    complexes) et doit toujours être vérifiée à la main.
# 4. Appliquer
alembic upgrade head
```

> ⚠️ Cette mise en place d'Alembic n'a pas pu être testée en exécution
> dans l'environnement où elle a été écrite (pas d'accès réseau pour
> installer les dépendances). Avant de l'utiliser en production, vérifiez
> localement que `alembic revision --autogenerate` ne détecte aucune
> différence juste après le `stamp head` initial (ce qui confirmerait que
> `alembic/env.py` reflète correctement `db/models.py`).

## Migration d'une base de données existante (montants en centimes)

Si vous mettez à jour un déploiement déjà en production (base créée par
une version antérieure du code, avec des colonnes `balance`/`price`/
`amount_usd` en float), lancez une seule fois, **avant** de redémarrer le
bot avec ce code :

```bash
python -m db.migrations.001_money_to_cents
```

Cette migration est idempotente (peut être relancée sans risque) et ne
supprime aucune donnée : les anciennes colonnes float sont renommées avec
le suffixe `_deprecated_float` et conservées pour vérification, jamais
supprimées automatiquement. Sur une base flambant neuve, elle n'a rien à
faire — `init_db()` crée directement le schéma à jour.

## Tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

Les tests de `tests/test_wallet_atomic.py` et `tests/test_ipn_idempotency.py`
font tourner de vraies opérations concurrentes (via `asyncio.gather`) sur
une base SQLite fichier temporaire, pour vérifier que le portefeuille et le
webhook IPN ne peuvent jamais produire de solde incohérent ou de
double-crédit.

## Déploiement Railway

1. Poussez ce dossier dans un dépôt Git (GitHub par exemple), connecté à
   un nouveau projet Railway.
2. Dans Railway → Variables, définissez :
   - `BOT_TOKEN` (obtenu via @BotFather)
   - `ADMIN_IDS` (vos IDs Telegram, séparés par des virgules — utilisez
     par exemple @userinfobot pour connaître le vôtre)
   - `NOWPAYMENTS_API_KEY` et `NOWPAYMENTS_IPN_SECRET` (dashboard
     NOWPayments → Store settings)
   - `SUPPORT_USERNAME`, `MIN_DEPOSIT_USD`, `LOW_STOCK_THRESHOLD` (optionnel)
3. **Stockage persistant** : si vous restez sur SQLite, ajoutez un volume
   Railway monté sur `/app/data` (sinon la base est perdue à chaque
   redéploiement). Pour plus de robustesse, vous pouvez brancher le
   plugin PostgreSQL de Railway et définir `DATABASE_URL` en
   `postgresql+asyncpg://...` — aucun changement de code nécessaire.
4. Dans NOWPayments, configurez l'URL IPN sur :
   `https://<votre-domaine-railway>.up.railway.app/ipn/nowpayments`
5. Railway détecte `Procfile` / `railway.json` et lance `python main.py`.
   Le serveur web démarre sur le port fourni par Railway (`$PORT`) pour
   le health check, en parallèle du polling Telegram.

## Premier démarrage

Au premier lancement, le catalogue initial du cahier des charges est
créé automatiquement en brouillon : catégorie **Fiches** (Starter Pack
50 fiches/20$, Pro Pack 100 fiches/40$, Ultimate Pack 250 fiches/70$) et
catégorie **Carte** (vide). Depuis `/admin` → Produits, envoyez les
vrais fichiers via **Restock** pour chaque pack, puis **Publiez**
chaque produit pour le rendre visible aux clients.

## Notes / limites connues

- Le webhook NOWPayments exige que `NOWPAYMENTS_IPN_SECRET` soit
  configuré ; sans lui, les crédits automatiques sont refusés par
  sécurité (aucun crédit ne peut être forgé sans signature valide).
- La réservation atomique de stock est garantie sur SQLite. Sur
  PostgreSQL avec un fort volume concurrent, envisagez d'ajouter
  `FOR UPDATE SKIP LOCKED` pour optimiser (le comportement reste correct
  tel quel, juste moins optimisé sous forte charge).
- Les statistiques et le dashboard sont calculés à la demande (pas de
  cache) : suffisant pour un volume normal de boutique Telegram.

# Carlo Brain : démarrage rapide

## Ce que c'est

Carlo Brain donne une mémoire et des garde-fous à Claude Code (et aussi à Codex, Gemini ou n'importe quel autre LLM). Tes notes vivent dans un dossier de fichiers Markdown que tu possèdes (un "vault", qu'on ouvre avec Obsidian). À chaque session, l'assistant sait qui tu es, sur quoi tu travailles et ce que tu as fait la dernière fois. Il prépare tes brouillons, mais il n'envoie jamais rien sans ton "go". Pas de serveur, pas de compte : juste Python et des fichiers.

## Installer

Il te faut macOS ou Linux, Python 3.9 ou plus, git, et Claude Code installé et connecté.

```bash
curl -fsSL https://raw.githubusercontent.com/Natanlsr3/carlo-brain/main/get.sh | bash
```

Le script clone le projet dans `~/carlo-brain`, installe avec les réglages par défaut (vault dans `~/carlo-vault`) et affiche la suite. Il n'utilise pas sudo et n'écrase jamais un dossier `~/carlo-brain` qui n'est pas un dépôt git. Si `carlo` n'est pas trouvé, copie la ligne qu'il affiche, puis ouvre un nouveau terminal. À la main, si tu préfères :

```bash
git clone https://github.com/Natanlsr3/carlo-brain && cd carlo-brain && ./install.sh
```

Ensuite, des modules optionnels qui marchent sans réglage :

```bash
carlo add agents-skills search review-loop health
carlo doctor
```

Attention : `proactive` (le briefing du matin) et `connectors` (WhatsApp, Mail, Google, Notion, Slack) ont besoin qu'une source soit branchée avant. Sans source, il n'y a rien à afficher. Le guide est dans [03-connect-your-sources.md](03-connect-your-sources.md) (en anglais).

## Tes 10 premières minutes

1. **Lance `claude` et écris `setup` (10 minutes).** Il cartographie ton ordinateur pendant qu'il t'interroge. Après ton accord, il lance un scan en lecture seule (`carlo scan`) des dossiers qu'il te liste : tes projets git, tes fichiers récents, tes applis de notes, les sources qui existent (Mail, Messages, Contacts, WhatsApp, Google, Notion) et les outils installés. Pendant ce temps il te demande qui tu es, comment tu aimes les réponses et ce que tu veux comme aide, puis te propose tes projets (« j'en ai trouvé 12, lesquels sont actifs ? »). Il te montre la carte (`00_System/MAP.md`) et les fiches projet qu'il va écrire, et les écrit quand tu réponds `yes`. Il te propose ensuite les connecteurs un par un. Trop long pour aujourd'hui ? Il réserve une session de 1 à 2 heures et reprend là où il s'est arrêté. Chaque semaine, un rafraîchissement te suggère les projets nouveaux ou inactifs, une question à la fois. Vie privée : le scan lit les noms, les dates et les premières lignes des README et des fichiers Markdown, jamais le contenu des mails ou des messages, ni les clés, `.env`, `.ssh` ou profils shell, et n'envoie rien nulle part.

2. **Relance une session** et lis le premier message. L'assistant dit qu'il est prêt et rappelle ce qu'il sait. Le premier jour il n'a pas d'historique, donc le message est court. Si rien ne s'affiche, lance `carlo doctor`.

3. **Essaie trois choses.**
   - Fais une petite tâche, quitte (`/exit`), relance `claude` et écris : `What did we do last session?` La réponse vient du journal de sessions.
   - Corrige-le une fois : `Answer in two lines maximum from now on. Remember this.` Il te montre le changement, tu réponds `yes`, et une ligne apparaît dans `00_System/CORRECTIONS.md`.
   - Dans un terminal : `carlo search "tarifs"` (un mot qui est dans ta carte). Il liste les fichiers et les lignes qui correspondent.

4. **Ajoute la suite, en sachant ce qu'il faut avant.**
   - `agents-skills`, `search`, `review-loop`, `health` : rien. Un simple `carlo add`.
   - `sync` : git. Un dépôt distant privé est facultatif.
   - `proactive` : une source branchée (pont WhatsApp, Apple Mail avec l'accès complet au disque, ou un export de todo).
   - `connectors` : choisis un connecteur et suis son guide.
   - `self-improve` et `night` : une connexion longue durée pour les tâches sans toi, et un essai à blanc d'abord.
   - `other-agents` : Codex CLI ou Gemini CLI installé, puis `carlo connect codex` ou `carlo connect gemini`.

## Pour aller plus loin

Les guides sont en anglais :

- [Tout ce que Carlo Brain sait faire, sur une page](00-features.md)
- [Installer](02-install.md) et [connecter tes sources](03-connect-your-sources.md)
- [Sécurité et vie privée](07-security-and-privacy.md), [coûts et limites](08-costs-and-limits.md), [FAQ](09-faq.md)
- Chaque module a son README dans `modules/<nom>/README.md`.

Pour tout retirer : `carlo uninstall`. Ton vault n'est jamais supprimé.

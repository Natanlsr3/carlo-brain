# Carlo Brain : démarrage rapide

## Ce que c'est

Carlo Brain donne une mémoire et des garde-fous à Claude Code (et aussi à Codex, Gemini ou n'importe quel autre LLM). Tes notes vivent dans un dossier de fichiers Markdown que tu possèdes (un "vault", qu'on ouvre avec Obsidian). À chaque session, l'assistant sait qui tu es, sur quoi tu travailles et ce que tu as fait la dernière fois. Il prépare tes brouillons, mais il n'envoie jamais rien sans ton "go". Pas de serveur, pas de compte : juste Python et des fichiers.

## Installer

Il te faut macOS ou Linux, Python 3.9 ou plus, git, et Claude Code installé et connecté.

```bash
git clone https://github.com/Natanlsr3/carlo-brain && cd carlo-brain
./install.sh
```

Le programme te pose trois questions (dossier du vault, nom de l'assistant, ton prénom). Sa dernière ligne te dit quoi faire ensuite. Si `carlo` n'est pas trouvé, copie la ligne qu'il affiche, puis ouvre un nouveau terminal. Ensuite, des modules optionnels qui marchent sans réglage :

```bash
carlo add agents-skills search review-loop health
carlo doctor
```

Attention : `proactive` (le briefing du matin) et `connectors` (WhatsApp, Mail, Google, Notion, Slack) ont besoin qu'une source soit branchée avant. Sans source, il n'y a rien à afficher. Le guide est dans [03-connect-your-sources.md](03-connect-your-sources.md) (en anglais).

## Tes 10 premières minutes

1. **Remplis ta carte (5 minutes).** Ouvre `00_System/MAP.md` dans ton vault (par défaut `~/carlo-vault`). Écris qui tu es, tes trois projets principaux et où se trouvent leurs fichiers. Sans ça, le premier démarrage est vide. Exemple :

   ```markdown
   **Who**: Sam, designer produit à Lyon. Aime les réponses courtes, travaille le soir.
   **Active projects** (read the entry file BEFORE working on a project):
   - Refonte du site : page tarifs, tests du paiement encore rouges. Entry file: `10_Projects/site/site.md`.
   - Clients freelance : deux factures à relancer. Entry file: `10_Projects/clients/clients.md`.
   - Cours d'espagnol : 20 minutes par jour. Entry file: `10_Projects/espagnol/espagnol.md`.
   **Where to look for more**: todo dans Rappels, contacts dans Contacts.
   ```

2. **Lance `claude`** et lis le premier message. L'assistant dit qu'il est prêt et rappelle ce qu'il sait. Le premier jour il n'a pas d'historique, donc le message est court. Si rien ne s'affiche, lance `carlo doctor`.

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

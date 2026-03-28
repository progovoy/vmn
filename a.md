VMN Product Strategy: Path to De Facto Standard                                                                                                          
                                                                                                                                                           
  Where vmn stands today                                                                                                                                   
                                                                                                                                                           
  - ~64 GitHub stars, ~980 PyPI downloads/month                                                                                                            
  - Competitors: semantic-release (23.5k stars), changesets (11.6k stars), commitizen-python (3.4k stars)                                                  
  - The gap is large, but vmn occupies a unique niche no one else serves                                                                                   
                                                                                                                                                           
  VMN's moat (features no competitor has)                                                                                                                  
                                                                                                                                                           
  ┌──────────────────────────────────────────┬──────────────────────────────────┬─────────────────────────────────────────────┐                            
  │                 Feature                  │        Nearest competitor        │                     Gap                     │                            
  ├──────────────────────────────────────────┼──────────────────────────────────┼─────────────────────────────────────────────┤                            
  │ Multi-repo dependency tracking           │ None                             │ Blue ocean                                  │
  ├──────────────────────────────────────────┼──────────────────────────────────┼─────────────────────────────────────────────┤                            
  │ vmn goto (state recovery)                │ None                             │ Blue ocean                                  │                            
  ├──────────────────────────────────────────┼──────────────────────────────────┼─────────────────────────────────────────────┤                            
  │ Root app / microservice topology         │ changesets (JS-only monorepo)    │ vmn is language-agnostic + cross-repo       │                            
  ├──────────────────────────────────────────┼──────────────────────────────────┼─────────────────────────────────────────────┤                            
  │ 4-segment hotfix versioning              │ None                             │ Unique                                      │
  ├──────────────────────────────────────────┼──────────────────────────────────┼─────────────────────────────────────────────┤                            
  │ Language-agnostic version auto-embedding │ Each tool does its own ecosystem │ vmn does npm + cargo + pyproject + any file │
  ├──────────────────────────────────────────┼──────────────────────────────────┼─────────────────────────────────────────────┤                            
  │ Offline/local file backend               │ None                             │ Niche but unique                            │
  └──────────────────────────────────────────┴──────────────────────────────────┴─────────────────────────────────────────────┘                            
                  
  Missing features to close the gap                                                                                                                        
                  
  P0 — Table stakes (blocking adoption)                                                                                                                    
                  
  1. Built-in changelog generation                                                                                                                         
  Every major competitor generates changelogs. vmn has conventional commits parsing already — it should output a CHANGELOG.md. Users shouldn't need
  git-cliff as a separate step. This is the single biggest gap.                                                                                            
                  
  2. GitHub Release creation                                                                                                                               
  When vmn stamp runs in CI, it should optionally create a GitHub Release with the generated notes. semantic-release, release-please, and
  python-semantic-release all do this. It's expected.                                                                                                      
                  
  3. vmn init-app --auto / zero-config first stamp                                                                                                         
  The init + init-app two-step ceremony before your first stamp is friction. Competitors offer npx semantic-release and it just works. Consider: if someone
   runs vmn stamp -r patch my_app and neither init nor init-app has been run, just do both automatically. Reduce the happy path to:                        
  pip install vmn 
  vmn stamp -r patch my_app   # just works                                                                                                                 
                                                                                                                                                           
  P1 — Competitive differentiators to amplify                                                                                                              
                                                                                                                                                           
  4. Comparison / migration pages                                                                                                                          
  Create dedicated docs:                                                                                                                                   
  - "vmn vs semantic-release"                                                                                                                              
  - "vmn vs release-please"                                                                                                                                
  - "vmn vs setuptools-scm"                                                                                                                                
  - "Migrating from standard-version" (deprecated, 8k stars, users actively looking)                                                                       
  - "Migrating from bump2version" (deprecated, users actively looking)                                                                                     
                                                                                                                                                           
  These capture search traffic. People Google "semantic-release alternative" and "standard-version replacement."                                           
                                                                                                                                                           
  5. Polish the GitHub Action                                                                                                                              
  vmn-action exists but has 14 stars and hasn't been updated recently. The GitHub Action is the #1 discovery channel for CI tools. It needs:               
  - Fresh release                                                                                                                                          
  - Rich README with copy-paste workflow examples                                                                                                          
  - Marketplace listing with good description/screenshots                                                                                                  
  - Examples for monorepo, multi-app, conventional commits                                                                                                 
                                                                                                                                                           
  6. uv / pipx one-liner install prominence                                                                                                                
  Lead the README with:                                                                                                                                    
  uvx vmn stamp -r patch my_app                                                                                                                            
  This is the 2026 way to run Python CLI tools. Being uv-native signals modernity.                                                                         
                                                                                                                                                           
  P2 — Expand the addressable market                                                                                                                       
                                                                                                                                                           
  7. CalVer support                                                                                                                                        
  Ubuntu, pip, Twisted, many infrastructure projects use calendar versioning (2025.03.28). No major versioning tool handles both SemVer and CalVer cleanly.
   Adding a --calver mode or configurable version scheme would be a differentiator.                                                                        
                  
  8. GitLab CI / Bitbucket Pipelines templates                                                                                                             
  release-please is GitHub-only. vmn works anywhere git works — this is an advantage, but only if there are copy-paste CI templates for GitLab and
  Bitbucket. Many enterprises use GitLab.                                                                                                                  
                  
  9. Package publishing hooks                                                                                                                              
  Not "vmn publishes to npm" — but a post_stamp hook system where users can configure:
  hooks:                                                                                                                                                   
    post_stamp:                                                                                                                                            
      - "npm publish"                                                                                                                                      
      - "cargo publish"                                                                                                                                    
  This way vmn orchestrates the full release without becoming ecosystem-specific.                                                                          
                                                                                                                                                           
  README strategy for virality                                                                                                                             
                                                                                                                                                           
  The current README is comprehensive but reads like a reference manual. Viral READMEs are structured differently:                                         
                                                                                                                                                           
  What to change                                                                                                                                           
                  
  1. Lead with the problem, not the solution                                                                                                               
  The opening should be a pain statement that makes people nod:
  ▎ "Your monorepo has 5 services. semantic-release can't version them independently. setuptools-scm is Python-only. GitVersion needs .NET. You just want  
  vmn stamp -r patch my_service and move on."                                                                                                              
                                                                                                                                                           
  2. Add an animated terminal GIF                                                                                                                          
  The current screenshot is a static image. Tools like https://github.com/charmbracelet/vhs or https://asciinema.org/ create terminal recordings. Show:    
  init, stamp, show, goto — in 15 seconds. This is the single highest-ROI README change.                                                                   
                                                                                                                                                           
  3. "Why vmn?" comparison table                                                                                                                           
  Right at the top, before any docs:
                                                                                                                                                           
  ┌───────────────────────┬──────────┬──────────────────┬────────────────┬────────────────┐                                                                
  │                       │   vmn    │ semantic-release │ release-please │ setuptools-scm │                                                                
  ├───────────────────────┼──────────┼──────────────────┼────────────────┼────────────────┤                                                                
  │ Language-agnostic     │ Yes      │ Node.js          │ Node.js        │ Python         │
  ├───────────────────────┼──────────┼──────────────────┼────────────────┼────────────────┤                                                                
  │ Monorepo              │ Yes      │ Plugin           │ Yes            │ No             │                                                                
  ├───────────────────────┼──────────┼──────────────────┼────────────────┼────────────────┤                                                                
  │ Multi-repo            │ Yes      │ No               │ No             │ No             │                                                                
  ├───────────────────────┼──────────┼──────────────────┼────────────────┼────────────────┤                                                                
  │ State recovery        │ vmn goto │ No               │ No             │ No             │
  ├───────────────────────┼──────────┼──────────────────┼────────────────┼────────────────┤                                                                
  │ Microservice topology │ Yes      │ No               │ No             │ No             │
  ├───────────────────────┼──────────┼──────────────────┼────────────────┼────────────────┤                                                                
  │ Conventional commits  │ Yes      │ Yes              │ Yes            │ No             │
  ├───────────────────────┼──────────┼──────────────────┼────────────────┼────────────────┤                                                                
  │ Changelog generation  │ Planned  │ Yes              │ Yes            │ No             │
  ├───────────────────────┼──────────┼──────────────────┼────────────────┼────────────────┤                                                                
  │ Zero-config           │ Coming   │ Yes              │ Yes            │ Yes            │
  └───────────────────────┴──────────┴──────────────────┴────────────────┴────────────────┘                                                                
                  
  People scan tables. This immediately communicates positioning.                                                                                           
                  
  4. Restructure the README flow                                                                                                                           
  Current: What → Playground → Contribute → Features → Examples → Detailed docs → Backends → Config
  Better: Problem → Why vmn (comparison) → 30-second GIF → Quick start (3 commands) → CI integration → Features → Detailed docs                            
                                                                                                                                                           
  Move "Contribute" and "Dev environment" to a separate CONTRIBUTING.md — it's noise for evaluators.                                                       
                                                                                                                                                           
  5. Add ecosystem badges for reach                                                                                                                        
  Get listed in:  
  - awesome-python                                                                                                                                         
  - awesome-devops                                                                                                                                         
  - awesome-git                                                                                                                                            
  - awesome-actions (for vmn-action)                                                                                                                       
                                    
  Each listing is a permanent backlink.                                                                                                                    
                                                                                                                                                           
  Priority roadmap                                                                                                                                         
                                                                                                                                                           
  ┌──────────┬─────────────────────────────────────────────────────┬───────────────────┬───────────────────────────────────────────┐                       
  │ Priority │                       Feature                       │      Effort       │                  Impact                   │
  ├──────────┼─────────────────────────────────────────────────────┼───────────────────┼───────────────────────────────────────────┤                       
  │ 1        │ README rewrite (comparison table, GIF, restructure) │ 1 week            │ High — first impression for every visitor │
  ├──────────┼─────────────────────────────────────────────────────┼───────────────────┼───────────────────────────────────────────┤                       
  │ 2        │ Auto-init on first stamp (zero-config)              │ Small code change │ Medium — removes friction                 │                       
  ├──────────┼─────────────────────────────────────────────────────┼───────────────────┼───────────────────────────────────────────┤                       
  │ 3        │ Built-in changelog generation                       │ Medium            │ High — table stakes                       │                       
  ├──────────┼─────────────────────────────────────────────────────┼───────────────────┼───────────────────────────────────────────┤                       
  │ 4        │ GitHub Release creation on stamp                    │ Small             │ Medium — expected feature                 │
  ├──────────┼─────────────────────────────────────────────────────┼───────────────────┼───────────────────────────────────────────┤                       
  │ 5        │ Comparison/migration pages                          │ Content work      │ High — SEO capture                        │
  ├──────────┼─────────────────────────────────────────────────────┼───────────────────┼───────────────────────────────────────────┤                       
  │ 6        │ Refresh vmn-action                                  │ Medium            │ High — discovery channel                  │
  ├──────────┼─────────────────────────────────────────────────────┼───────────────────┼───────────────────────────────────────────┤                       
  │ 7        │ Post-stamp hooks                                    │ Small             │ Medium — extensibility                    │
  ├──────────┼─────────────────────────────────────────────────────┼───────────────────┼───────────────────────────────────────────┤                       
  │ 8        │ CalVer support                                      │ Medium            │ Medium — expands TAM                      │
  ├──────────┼─────────────────────────────────────────────────────┼───────────────────┼───────────────────────────────────────────┤                       
  │ 9        │ GitLab/Bitbucket CI templates                       │ Content work      │ Medium — enterprise capture               │
  └──────────┴─────────────────────────────────────────────────────┴───────────────────┴───────────────────────────────────────────┘                       
                  
  The positioning line                                                                                                                                     
                  
  vmn's unique angle in one sentence:                                                                                                                      
                  
  ▎ "The only versioning tool built for polyglot monorepos, multi-repo dependencies, and microservice topologies — language-agnostic, git-native, zero     
  lock-in."       
                                                                                                                                                           
  Every other tool is either ecosystem-locked (semantic-release=JS, setuptools-scm=Python, GitVersion=.NET) or monorepo-only (changesets). vmn is the only 
  tool that works across languages AND across repositories. That's the message.

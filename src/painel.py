"""Geração do Painel HTML estático (dashboard de relatórios e histórico do jornal-eink)."""
import datetime as dt
import html
import json
from pathlib import Path
import webbrowser

from .config import resolver_caminho


def coletar_relatorios(pasta_relatorios: Path) -> list[dict]:
    """Carrega todos os relatórios JSON da pasta, ordenados por data decrescente."""
    if not pasta_relatorios.exists() or not pasta_relatorios.is_dir():
        return []
    relatorios = []
    for arq in pasta_relatorios.glob("*.relatorio.json"):
        try:
            dados = json.loads(arq.read_text(encoding="utf-8"))
            dados["_arquivo_relatorio"] = arq.name
            relatorios.append(dados)
        except Exception:
            continue
    # Ordena decrescente pela data (ou gerado_em)
    relatorios.sort(key=lambda r: (r.get("data", ""), r.get("gerado_em", "")), reverse=True)
    return relatorios


def coletar_historico(caminho_hist: Path) -> list[dict]:
    """Carrega os itens do histórico ordenados por data decrescente."""
    if not caminho_hist.exists():
        return []
    try:
        registros = json.loads(caminho_hist.read_text(encoding="utf-8"))
        if not isinstance(registros, list):
            return []
    except Exception:
        return []
    # Normaliza cada item para facilitar filtragem e busca
    itens = []
    for r in registros:
        tipo = r.get("tipo")
        if not tipo:
            tipo = "wikipedia"
        tema = r.get("tema") or ""
        fonte = r.get("fonte") or ("Wikipédia" if tipo == "wikipedia" else "")
        titulo = r.get("titulo") or ""
        url = r.get("url") or ""
        if not url and tipo == "wikipedia" and titulo:
            url = f"https://pt.wikipedia.org/wiki/{html.escape(titulo).replace(' ', '_')}"
        data = r.get("data") or ""
        itens.append({
            "tipo": tipo,
            "tema": tema,
            "fonte": fonte,
            "titulo": titulo,
            "url": url,
            "data": data,
            "pageid": r.get("pageid"),
        })
    itens.sort(key=lambda x: x["data"], reverse=True)
    return itens


def _montar_estatisticas(relatorios: list[dict], historico: list[dict]) -> dict:
    """Calcula estatísticas agregadas do acervo e das edições."""
    total_edicoes = len(relatorios)
    total_itens_hist = len(historico)
    
    por_tipo = {}
    por_tema = {}
    for it in historico:
        tipo = it["tipo"]
        por_tipo[tipo] = por_tipo.get(tipo, 0) + 1
        if it["tema"]:
            por_tema[it["tema"]] = por_tema.get(it["tema"], 0) + 1
            
    # Temas ordenados pelo número de aparições
    temas_ordenados = sorted(por_tema.items(), key=lambda x: x[1], reverse=True)
    
    # Fontes com alerta recente (na última edição)
    fontes_esgotadas_ultima = []
    if relatorios:
        ult = relatorios[0]
        fontes_esgotadas_ultima = ult.get("fontes_sem_item") or []

    return {
        "total_edicoes": total_edicoes,
        "total_itens_hist": total_itens_hist,
        "por_tipo": por_tipo,
        "temas_ranking": temas_ordenados,
        "fontes_esgotadas_ultima": fontes_esgotadas_ultima,
    }


def renderizar_painel_html(relatorios: list[dict], historico: list[dict], cfg_jornal: dict) -> str:
    """Gera o HTML único e autocontido com CSS e JavaScript embutidos."""
    stats = _montar_estatisticas(relatorios, historico)
    nome_jornal = cfg_jornal.get("titulo", "Jornal Semanal")
    agora = dt.datetime.now().strftime("%d/%m/%Y às %H:%M")

    # Injetamos os dados brutos como JSON seguro dentro de script tags para o JS dinâmico
    json_relatorios = json.dumps(relatorios, ensure_ascii=False)
    json_historico = json.dumps(historico, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Painel do Leitor · {html.escape(nome_jornal)}</title>
  <style>
    :root {{
      --bg: #fbfbf9;
      --card-bg: #ffffff;
      --text: #222222;
      --text-muted: #666666;
      --border: #e2e2dc;
      --accent: #2b4c7e;
      --accent-bg: #eef3f9;
      --badge-wiki: #4a5568;
      --badge-escolha: #2b6cb0;
      --badge-noticia: #744210;
      --badge-dw: #22543d;
      --alert-bg: #fff5f5;
      --alert-border: #feb2b2;
      --alert-text: #9b2c2c;
      --success-bg: #f0fff4;
      --success-border: #9ae6b4;
      --success-text: #22543d;
      --font-serif: "Newsreader", "Georgia", "Cambria", serif;
      --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      --font-mono: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
    }}

    @media (prefers-color-scheme: dark) {{
      :root {{
        --bg: #151618;
        --card-bg: #1e2022;
        --text: #ececec;
        --text-muted: #9e9e9e;
        --border: #33363a;
        --accent: #78a9ff;
        --accent-bg: #1b263b;
        --badge-wiki: #3d4450;
        --badge-escolha: #244973;
        --badge-noticia: #5f370e;
        --badge-dw: #1c4532;
        --alert-bg: #2d1818;
        --alert-border: #742a2a;
        --alert-text: #feb2b2;
        --success-bg: #162a1c;
        --success-border: #22543d;
        --success-text: #9ae6b4;
      }}
    }}

    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background-color: var(--bg);
      color: var(--text);
      font-family: var(--font-sans);
      line-height: 1.5;
      padding: 1.5rem 1rem 3rem 1rem;
    }}

    .container {{
      max-width: 1040px;
      margin: 0 auto;
    }}

    header {{
      border-bottom: 2px solid var(--border);
      padding-bottom: 1.25rem;
      margin-bottom: 1.5rem;
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: baseline;
      gap: 0.5rem;
    }}

    header h1 {{
      font-family: var(--font-serif);
      font-size: 1.9rem;
      letter-spacing: -0.02em;
      font-weight: 700;
    }}

    header .subtitle {{
      color: var(--text-muted);
      font-size: 0.88rem;
    }}

    /* Métricas no topo */
    .metrics-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
      gap: 1rem;
      margin-bottom: 1.5rem;
    }}

    .metric-card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 1rem;
    }}

    .metric-card .label {{
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
    }}

    .metric-card .value {{
      font-size: 1.6rem;
      font-weight: 700;
      font-family: var(--font-serif);
      margin-top: 0.25rem;
    }}

    .metric-card .detail {{
      font-size: 0.8rem;
      color: var(--text-muted);
      margin-top: 0.2rem;
    }}

    /* Alertas */
    .alert-box {{
      background: var(--alert-bg);
      border: 1px solid var(--alert-border);
      color: var(--alert-text);
      padding: 0.85rem 1rem;
      border-radius: 6px;
      margin-bottom: 1.5rem;
      font-size: 0.9rem;
    }}

    .alert-box strong {{ font-weight: 600; }}

    /* Abas */
    .tabs {{
      display: flex;
      gap: 0.5rem;
      border-bottom: 1px solid var(--border);
      margin-bottom: 1.5rem;
    }}

    .tab-btn {{
      background: none;
      border: none;
      color: var(--text-muted);
      font-size: 0.95rem;
      font-weight: 600;
      padding: 0.6rem 1rem;
      cursor: pointer;
      border-bottom: 2px solid transparent;
      margin-bottom: -1px;
      transition: color 0.15s, border-color 0.15s;
    }}

    .tab-btn:hover {{
      color: var(--text);
    }}

    .tab-btn.active {{
      color: var(--accent);
      border-bottom-color: var(--accent);
    }}

    .tab-panel {{
      display: none;
    }}

    .tab-panel.active {{
      display: block;
    }}

    /* Cards e Blocos */
    .card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 1.25rem;
      margin-bottom: 1.25rem;
    }}

    .card h2 {{
      font-family: var(--font-serif);
      font-size: 1.3rem;
      margin-bottom: 0.75rem;
    }}

    /* Edições */
    .edicao-header {{
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 0.5rem;
      border-bottom: 1px solid var(--border);
      padding-bottom: 0.75rem;
      margin-bottom: 0.75rem;
    }}

    .edicao-title {{
      font-family: var(--font-serif);
      font-size: 1.25rem;
      font-weight: 700;
    }}

    .edicao-meta {{
      font-size: 0.85rem;
      color: var(--text-muted);
      font-family: var(--font-mono);
    }}

    .secoes-list {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
      gap: 0.75rem;
      margin-top: 0.75rem;
    }}

    .secao-item {{
      background: var(--bg);
      border: 1px solid var(--border);
      border-radius: 4px;
      padding: 0.6rem 0.8rem;
      font-size: 0.88rem;
    }}

    .secao-item.vazia {{
      border-color: var(--alert-border);
      background: var(--alert-bg);
      color: var(--alert-text);
    }}

    .secao-nome {{
      font-weight: 600;
      margin-bottom: 0.25rem;
      display: flex;
      justify-content: space-between;
    }}

    .fontes-detalhe {{
      font-size: 0.8rem;
      color: var(--text-muted);
    }}

    .qualidade-badge {{
      display: inline-block;
      font-size: 0.8rem;
      padding: 0.2rem 0.5rem;
      border-radius: 4px;
      background: var(--accent-bg);
      color: var(--accent);
      font-family: var(--font-mono);
      margin-top: 0.5rem;
    }}

    /* Acervo / Filtros */
    .filtros-bar {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.75rem;
      margin-bottom: 1rem;
      align-items: center;
    }}

    .busca-input {{
      flex: 1;
      min-width: 240px;
      padding: 0.6rem 0.9rem;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: var(--card-bg);
      color: var(--text);
      font-size: 0.95rem;
    }}

    .busca-input:focus {{
      outline: 2px solid var(--accent);
    }}

    .pills-group {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.35rem;
    }}

    .pill-btn {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      color: var(--text-muted);
      border-radius: 20px;
      padding: 0.35rem 0.75rem;
      font-size: 0.8rem;
      cursor: pointer;
      transition: all 0.15s;
    }}

    .pill-btn:hover {{
      color: var(--text);
      border-color: var(--text-muted);
    }}

    .pill-btn.active {{
      background: var(--accent);
      color: #ffffff;
      border-color: var(--accent);
    }}

    /* Tabela do Histórico */
    .tabela-wrapper {{
      overflow-x: auto;
    }}

    table.acervo-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.88rem;
      text-align: left;
    }}

    table.acervo-table th {{
      border-bottom: 2px solid var(--border);
      padding: 0.6rem 0.75rem;
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
    }}

    table.acervo-table td {{
      border-bottom: 1px solid var(--border);
      padding: 0.65rem 0.75rem;
      vertical-align: middle;
    }}

    table.acervo-table tr:hover td {{
      background: var(--accent-bg);
    }}

    .tag-tipo {{
      display: inline-block;
      font-size: 0.72rem;
      font-weight: 600;
      text-transform: uppercase;
      padding: 0.15rem 0.45rem;
      border-radius: 3px;
      color: #ffffff;
    }}
    .tag-tipo.wikipedia {{ background: var(--badge-wiki); }}
    .tag-tipo.escolha {{ background: var(--badge-escolha); }}
    .tag-tipo.noticia {{ background: var(--badge-noticia); }}
    .tag-tipo.dw {{ background: var(--badge-dw); }}

    .artigo-link {{
      color: var(--text);
      text-decoration: none;
      font-weight: 500;
    }}

    .artigo-link:hover {{
      color: var(--accent);
      text-decoration: underline;
    }}

    .contador-itens {{
      font-size: 0.85rem;
      color: var(--text-muted);
      margin-top: 0.5rem;
    }}

    /* Responsividade */
    @media (max-width: 600px) {{
      body {{ padding: 1rem 0.5rem; }}
      .metrics-grid {{ grid-template-columns: 1fr 1fr; }}
      .secoes-list {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div>
        <h1>{html.escape(nome_jornal)}</h1>
        <div class="subtitle">Painel de Relatórios & Histórico · Gerado em {agora}</div>
      </div>
    </header>

    <!-- Métricas Gerais -->
    <section class="metrics-grid">
      <div class="metric-card">
        <div class="label">Edições Geradas</div>
        <div class="value">{stats['total_edicoes']}</div>
        <div class="detail">{f"Última em {relatorios[0].get('data', '—')}" if relatorios else "Nenhum relatório"}</div>
      </div>
      <div class="metric-card">
        <div class="label">Itens no Acervo</div>
        <div class="value">{stats['total_itens_hist']}</div>
        <div class="detail">histórico acumulado</div>
      </div>
      <div class="metric-card">
        <div class="label">Wikipédia</div>
        <div class="value">{stats['por_tipo'].get('wikipedia', 0)}</div>
        <div class="detail">{len(stats['temas_ranking'])} temas ativos</div>
      </div>
      <div class="metric-card">
        <div class="label">Escolhas do Editor</div>
        <div class="value">{stats['por_tipo'].get('escolha', 0)}</div>
        <div class="detail">{stats['por_tipo'].get('noticia', 0)} notícias · {stats['por_tipo'].get('dw', 0)} DW</div>
      </div>
    </section>

    <!-- Alertas de fontes sem item na edição mais recente -->
    {"".join(f'''<div class="alert-box">
      <strong>Atenção:</strong> Na última edição ({relatorios[0].get("data")}), a fonte <em>{html.escape(f.get("fonte", ""))}</em>
      na seção <em>{html.escape(f.get("secao", ""))}</em> ficou sem itens (motivo: <code>{html.escape(str(f.get("motivo", "")))}</code>).
      Pode ser necessário adicionar novas categorias em <code>config.yaml</code>.
    </div>''' for f in stats['fontes_esgotadas_ultima']) if stats['fontes_esgotadas_ultima'] else ""}

    <!-- Navegação por Abas -->
    <div class="tabs">
      <button class="tab-btn active" data-tab="tab-edicoes">Edições & Relatórios</button>
      <button class="tab-btn" data-tab="tab-acervo">Acervo de Artigos ({stats['total_itens_hist']})</button>
      <button class="tab-btn" data-tab="tab-temas">Distribuição de Temas</button>
    </div>

    <!-- Aba 1: Edições e Relatórios -->
    <div id="tab-edicoes" class="tab-panel active">
      <div id="lista-edicoes"></div>
    </div>

    <!-- Aba 2: Acervo e Histórico com Busca -->
    <div id="tab-acervo" class="tab-panel">
      <div class="filtros-bar">
        <input type="text" id="campo-busca" class="busca-input" placeholder="Buscar por título, tema ou fonte..." autocomplete="off">
        <div class="pills-group" id="filtros-tipo">
          <button class="pill-btn active" data-tipo="todos">Todos</button>
          <button class="pill-btn" data-tipo="wikipedia">Wikipédia</button>
          <button class="pill-btn" data-tipo="escolha">Editor</button>
          <button class="pill-btn" data-tipo="noticia">Notícias</button>
          <button class="pill-btn" data-tipo="dw">DW</button>
        </div>
      </div>
      <div class="contador-itens" id="contador-visiveis">Mostrando {stats['total_itens_hist']} itens</div>
      <div class="tabela-wrapper" style="margin-top: 0.5rem;">
        <table class="acervo-table">
          <thead>
            <tr>
              <th style="width: 100px;">Data</th>
              <th style="width: 90px;">Tipo</th>
              <th style="width: 140px;">Tema / Fonte</th>
              <th>Título</th>
            </tr>
          </thead>
          <tbody id="corpo-acervo"></tbody>
        </table>
      </div>
    </div>

    <!-- Aba 3: Distribuição de Temas -->
    <div id="tab-temas" class="tab-panel">
      <div class="card">
        <h2>Frequência de Artigos por Tema (Wikipédia)</h2>
        <div class="secoes-list" style="margin-top: 1rem;">
          {"".join(f'''<div class="secao-item">
            <div class="secao-nome">
              <span>{html.escape(tema)}</span>
              <strong>{qtd}</strong>
            </div>
            <div class="fontes-detalhe">artigo(s) publicado(s)</div>
          </div>''' for tema, qtd in stats['temas_ranking'])}
        </div>
      </div>
    </div>

  </div>

  <!-- Dados Injetados -->
  <script id="dados-relatorios" type="application/json">{json_relatorios}</script>
  <script id="dados-historico" type="application/json">{json_historico}</script>

  <script>
    (function() {{
      const relatorios = JSON.parse(document.getElementById('dados-relatorios').textContent || '[]');
      const historico = JSON.parse(document.getElementById('dados-historico').textContent || '[]');

      // 1. Gerenciamento de Abas
      document.querySelectorAll('.tab-btn').forEach(btn => {{
        btn.addEventListener('click', () => {{
          document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
          document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
          btn.classList.add('active');
          const painelId = btn.getAttribute('data-tab');
          const painel = document.getElementById(painelId);
          if (painel) painel.classList.add('active');
        }});
      }});

      // 2. Renderização das Edições
      const containerEdicoes = document.getElementById('lista-edicoes');
      if (relatorios.length === 0) {{
        containerEdicoes.innerHTML = '<div class="card"><p style="color:var(--text-muted)">Nenhum relatório encontrado na pasta de relatórios.</p></div>';
      }} else {{
        let htmlEdicoes = '';
        relatorios.forEach(rel => {{
          const numEdicao = rel.numero_edicao ? `Edição Nº ${{rel.numero_edicao}}` : 'Edição';
          const arqNome = rel.arquivo || '';
          const q = rel.qualidade || {{}};
          const qResumo = q.backend ? `Qualidade (${{q.backend}}): ${{q.aprovados || 0}} aprovados / ${{q.avaliados || 0}} avaliados (min ${{q.classe_minima || 'C'}})` : '';
          
          let secoesHtml = '';
          (rel.secoes || []).forEach(s => {{
            const vaziaCls = s.vazia ? 'vazia' : '';
            const statusTxt = s.vazia ? ' — VAZIA' : '';
            const fontesTxt = (s.fontes || []).map(f => {{
              return f.motivo ? `${{f.fonte}} (0 - ${{f.motivo}})` : `${{f.fonte}} (${{f.itens}})`;
            }}).join(', ');

            secoesHtml += `
              <div class="secao-item ${{vaziaCls}}">
                <div class="secao-nome">
                  <span>${{escapeHtml(s.nome)}}${{statusTxt}}</span>
                  <span>${{s.itens}} item(ns)</span>
                </div>
                <div class="fontes-detalhe">${{escapeHtml(fontesTxt)}}</div>
              </div>
            `;
          }});

          htmlEdicoes += `
            <div class="card">
              <div class="edicao-header">
                <div>
                  <div class="edicao-title">${{numEdicao}} · ${{rel.data}}</div>
                  <div class="edicao-meta">${{escapeHtml(arqNome)}} · gerado em ${{rel.gerado_em || '—'}}</div>
                </div>
                ${{qResumo ? `<div class="qualidade-badge">${{escapeHtml(qResumo)}}</div>` : ''}}
              </div>
              <div class="secoes-list">${{secoesHtml}}</div>
            </div>
          `;
        }});
        containerEdicoes.innerHTML = htmlEdicoes;
      }}

      // 3. Renderização do Acervo e Busca Dinâmica
      const corpoAcervo = document.getElementById('corpo-acervo');
      const campoBusca = document.getElementById('campo-busca');
      const contadorVisiveis = document.getElementById('contador-visiveis');
      let tipoAtivo = 'todos';

      function renderizarTabela() {{
        const termo = (campoBusca.value || '').trim().toLowerCase();
        let filtrados = historico.filter(it => {{
          if (tipoAtivo !== 'todos' && it.tipo !== tipoAtivo) return false;
          if (!termo) return true;
          return (it.titulo && it.titulo.toLowerCase().includes(termo)) ||
                 (it.tema && it.tema.toLowerCase().includes(termo)) ||
                 (it.fonte && it.fonte.toLowerCase().includes(termo));
        }});

        contadorVisiveis.textContent = `Mostrando ${{filtrados.length}} de ${{historico.length}} itens`;

        if (filtrados.length === 0) {{
          corpoAcervo.innerHTML = '<tr><td colspan="4" style="text-align:center; padding:1.5rem; color:var(--text-muted)">Nenhum artigo encontrado para o filtro aplicado.</td></tr>';
          return;
        }}

        // Renderiza no máximo os primeiros 200 itens para ultra performance se a lista for gigante
        const limite = Math.min(filtrados.length, 250);
        let rows = '';
        for (let i = 0; i < limite; i++) {{
          const it = filtrados[i];
          const temaOuFonte = it.tema || it.fonte || '—';
          const link = it.url ? `<a href="${{escapeHtml(it.url)}}" target="_blank" rel="noopener" class="artigo-link">${{escapeHtml(it.titulo)}}</a>` : escapeHtml(it.titulo);
          rows += `
            <tr>
              <td style="font-family:var(--font-mono); font-size:0.8rem; color:var(--text-muted);">${{it.data}}</td>
              <td><span class="tag-tipo ${{it.tipo}}">${{it.tipo}}</span></td>
              <td>${{escapeHtml(temaOuFonte)}}</td>
              <td>${{link}}</td>
            </tr>
          `;
        }}
        if (filtrados.length > limite) {{
          rows += `<tr><td colspan="4" style="text-align:center; padding:0.75rem; color:var(--text-muted); font-size:0.8rem;">(Exibindo primeiros ${{limite}} resultados de ${{filtrados.length}}. Refine a busca para encontrar itens específicos.)</td></tr>`;
        }}
        corpoAcervo.innerHTML = rows;
      }}

      campoBusca.addEventListener('input', renderizarTabela);

      document.querySelectorAll('#filtros-tipo .pill-btn').forEach(btn => {{
        btn.addEventListener('click', () => {{
          document.querySelectorAll('#filtros-tipo .pill-btn').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          tipoAtivo = btn.getAttribute('data-tipo');
          renderizarTabela();
        }});
      }});

      function escapeHtml(str) {{
        if (!str) return '';
        return String(str)
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/"/g, '&quot;')
          .replace(/'/g, '&#039;');
      }}

      // Inicializa a tabela
      renderizarTabela();
    }})();
  </script>
</body>
</html>
"""


def gerar_painel(cfg: dict, abrir: bool = False) -> Path:
    """Gera o arquivo `painel.html` com dados dos relatórios e do histórico."""
    rcfg = cfg.get("relatorio") or {}
    pasta_relatorios = resolver_caminho(rcfg.get("pasta", "relatorios"))
    
    hcfg = cfg.get("historico") or {}
    caminho_hist = resolver_caminho(hcfg.get("arquivo", "historico.json"))

    pcfg = cfg.get("painel") or {}
    destino_relativo = pcfg.get("arquivo", pasta_relatorios / "painel.html")
    destino = resolver_caminho(destino_relativo)
    destino.parent.mkdir(parents=True, exist_ok=True)

    relatorios = coletar_relatorios(pasta_relatorios)
    historico = coletar_historico(caminho_hist)

    conteudo_html = renderizar_painel_html(relatorios, historico, cfg)

    tmp = destino.with_suffix(".tmp")
    tmp.write_text(conteudo_html, encoding="utf-8")
    tmp.replace(destino)

    if abrir:
        try:
            webbrowser.open(destino.as_uri())
        except Exception:
            pass

    return destino

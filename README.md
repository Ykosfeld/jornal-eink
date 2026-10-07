# jornal-eink

Gera toda semana um **.epub** personalizado, no formato de jornal, para ler em e-reader (feito para o Xteink X4 com firmware CrossPoint, tela de 480 px, mas funciona em qualquer leitor de epub).

> 🤖 **Aviso:** este projeto é desenvolvido com auxílio de ferramentas de IA (Claude, da Anthropic), tanto no planejamento quanto na escrita do código. Todo o código é revisado e testado por mim, mas pode conter erros ou soluções pouco convencionais.

## O que tem em cada edição

- **Notícias**: itens recentes de feeds RSS/Atom (ou arquivos OPML) à sua escolha, revezando entre as fontes.
- **Almanaque**: efemérides da semana, curiosidades, datas e destaques da Wikipédia em inglês marcados `[EN]`.
- **Curiosidades**: um artigo da Wikipédia em português para cada tema configurado (matemática, física, astronomia, música, aves, cinema etc.), normalmente sorteado; opcionalmente, Cinema pode priorizar artigos relacionados a filmes recentes do Letterboxd. Com imagem de destaque em tons de cinza e fórmulas convertidas para MathML.
- **Deutsch üben**: artigos do *Top-Thema mit Vokabeln* da DW (nível B1), com manuscrito e glossário.
- **Escolha do Editor**: seleção manual de artigos ou páginas da web, com suporte a uma **extensão de navegador** própria para salvar links com um clique e detectar automaticamente o idioma.
- **Capa generativa**: mapa topográfico em tons de cinza, gerado a partir dos artigos e da data da edição (mesma edição, mesma capa).
- **Sem repetição**: um histórico em JSON evita que o mesmo artigo ou notícia apareça em duas edições.

## Requisitos

- Python 3.10+
- Dependências em `requirements.txt`
- Opcional: fonte DejaVu Serif instalada (usada no título da capa; há fallback)

## Instalação

```bash
git clone https://github.com/Ykosfeld/jornal-eink.git
cd jornal-eink
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Uso

```bash
python main.py                                  # gera a edição da semana
python main.py --validar                        # testa as categorias da Wikipédia do config
python main.py --validar-feeds                  # testa os feeds de notícias e da DW
python main.py --semente 42 --sem-historico     # teste reprodutível, sem mexer no histórico
python main.py --validar-qualidade               # fumaça do backend Lift Wing
```

O epub é salvo em `saida/` (configurável) com o nome `jornal_AAAA-MM-DD.epub`.

## Configuração

Tudo fica no `config.yaml`:

| Chave | Para que serve |
|---|---|
| `titulo`, `autor`, `idioma` | Metadados do epub e título da capa |
| `primeira_edicao` | Data da edição nº 1 (a capa mostra "Nº N") |
| `saida` | Pasta de destino dos epubs |
| `wikipedia` | Tamanho mínimo/máximo, profundidade de busca e classe mínima de qualidade Lift Wing |
| `temas` | Temas e categorias-raiz da Wikipédia usadas no sorteio |
| `imagens` | Tamanho e qualidade das imagens (ajustados para e-ink) |
| `noticias` | Feeds/OPML, itens por feed e janela de dias |
| `dw` | Feed, quantidade de artigos e opções do manuscrito |
| `almanaque` | Efemérides da semana, imagem e destaques da Wikipédia |
| `personalizacao_cultural.letterboxd` | Prioriza artigos de Cinema pelos filmes assistidos, nota, data e créditos na Wikipédia |
| `secoes` | Fontes de cada seção e ordem no epub; coloque `almanaque` primeiro para exibi-lo logo após a capa |
| `historico` | Arquivo do histórico e por quanto tempo lembrar |
| `arquivo_morto` | Mantém edições recentes na raiz de `saida` e arquiva as demais |
| `leitura` | Caracteres por minuto usados nos tempos estimados |
| `sumario` | Ativa o capítulo "Nesta edição" após a capa |
| `divisorias` | Ativa páginas divisórias por seção e define o mínimo de itens |

Para ativar a personalização de Cinema, defina `personalizacao_cultural.ativar`
e `personalizacao_cultural.letterboxd.ativar` como `true` e configure
`feed_url` com a URL RSS do seu perfil. Por padrão são considerados os filmes
assistidos nos últimos 7 dias, ordenados por nota e depois pela data assistida.
Os artigos relacionados respeitam o histórico e o filtro Lift Wing; se não houver
uma relação elegível ou o feed falhar, o sorteio normal continua como fallback.

O filtro Lift Wing do sorteio de artigos é configurável em `wikipedia.filtro_qualidade`.
Ele avalia a revisão atual do candidato (classes Stub, Start, C, B, GA e FA) e,
por padrão, aceita B ou superior. Candidatos abaixo do limiar são descartados e
o sorteio tenta outro; se o serviço falhar, um disjuntor aceita candidatos sem
filtro pelo restante da edição e registra isso no relatório. Use `ativar: false`
para desligar o filtro. O token opcional fica em `WIKIMEDIA_API_TOKEN`, nunca no
`config.yaml`.

O arquivo morto só roda após uma publicação normal. A raiz de `saida` fica com
a edição atual; as demais são movidas para `saida/anteriores`, que aparece como
subpasta no catálogo OPDS. `--sem-historico` não move arquivos.

## Automação e entrega

O projeto é executado automaticamente no host atual através de um timer do `systemd`, garantindo a geração periódica e logs melhores em comparação ao antigo setup em cron (anteriormente em um Raspberry Pi).

Exemplo de arquivo de serviço (`~/.config/systemd/user/jornal-eink.service`):

```ini
[Unit]
Description=Gerador do Jornal e-Ink

[Service]
Type=oneshot
WorkingDirectory=%h/Projetos/jornal-eink
ExecStart=%h/Projetos/jornal-eink/.venv/bin/python main.py
```

E o timer (`~/.config/systemd/user/jornal-eink.timer`) para rodar aos domingos às 7h:

```ini
[Unit]
Description=Rodar Jornal e-Ink todo domingo

[Timer]
OnCalendar=Sun *-*-* 07:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

Para receber o epub no e-reader por Wi-Fi, aponte `saida` para uma pasta servida por um catálogo OPDS, como o [dir2opds](https://github.com/dubyte/dir2opds), e adicione a URL do catálogo no leitor.

## Estrutura

```
main.py              # CLI
config.yaml          # configuração
src/
  almanaque.py      # coleta de efemérides e destaques da Wikipédia
  pipeline.py        # orquestra coleta -> epub -> histórico
  itens.py           # adapta coletores ao formato uniforme de seção
  qualidade.py       # filtro Lift Wing por edição
  leitura.py         # estimativa uniforme de tempo de leitura
  arquivo.py         # rotação de edições publicadas
  layout.py          # valida fontes e ordena seções configuráveis
  wikipedia.py       # sorteio e limpeza de artigos
  feeds.py           # notícias (RSS/OPML) e DW
  formulas.py        # LaTeX -> MathML
  capa.py            # capa generativa
  epub_builder.py    # montagem do epub
  historico.py       # controle de itens já publicados
  escolha.py         # escolhas do editor
  letterboxd.py      # personalização cultural de Cinema
  relatorio.py       # relatório JSON e resumo
docs/TODO.md         # ideias e pendências
```

## Roadmap

Veja [`docs/TODO.md`](docs/TODO.md).

## Créditos e licenças de conteúdo

- Textos e imagens da Wikipédia estão sob [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) e são creditados em cada capítulo.
- Notícias e conteúdo da DW pertencem aos seus respectivos autores; o uso aqui é pessoal, e cada capítulo traz o link da fonte.
# jornal-eink

Gera toda semana um **.epub** personalizado, no formato de jornal, para ler em e-reader (feito para o Xteink X4 com firmware CrossPoint, tela de 480 px, mas funciona em qualquer leitor de epub).

> 🤖 **Aviso:** este projeto é desenvolvido com auxílio de ferramentas de IA (Claude, da Anthropic), tanto no planejamento quanto na escrita do código. Todo o código é revisado e testado por mim, mas pode conter erros ou soluções pouco convencionais.

## O que tem em cada edição

- **Notícias**: itens recentes de feeds RSS/Atom (ou arquivos OPML) à sua escolha, revezando entre as fontes.
- **Almanaque**: efemérides da semana, curiosidades, datas e destaques da Wikipédia em inglês marcados `[EN]`.
- **Curiosidades**: um artigo da Wikipédia em português para cada tema configurado (matemática, física, astronomia, música, aves, cinema etc.), normalmente sorteado; opcionalmente, Cinema pode priorizar artigos relacionados a filmes recentes do Letterboxd. Com imagem de destaque em tons de cinza e fórmulas convertidas para MathML.
- **Deutsch üben**: artigos do *Top-Thema mit Vokabeln* da DW (nível B1), com manuscrito e glossário.
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
```

O epub é salvo em `saida/` (configurável) com o nome `jornal_AAAA-MM-DD.epub`.

## Configuração

Tudo fica no `config.yaml`:

| Chave | Para que serve |
|---|---|
| `titulo`, `autor`, `idioma` | Metadados do epub e título da capa |
| `primeira_edicao` | Data da edição nº 1 (a capa mostra "Nº N") |
| `saida` | Pasta de destino dos epubs |
| `wikipedia` | Tamanho mínimo/máximo, profundidade de busca e classe mínima de qualidade ORES |
| `temas` | Temas e categorias-raiz da Wikipédia usadas no sorteio |
| `imagens` | Tamanho e qualidade das imagens (ajustados para e-ink) |
| `noticias` | Feeds/OPML, itens por feed e janela de dias |
| `dw` | Feed, quantidade de artigos e opções do manuscrito |
| `almanaque` | Efemérides da semana, imagem e destaques da Wikipédia |
| `personalizacao_cultural.letterboxd` | Prioriza artigos de Cinema pelos filmes assistidos, nota, data e créditos na Wikipédia |
| `secoes` | Fontes de cada seção e ordem no epub; coloque `almanaque` primeiro para exibi-lo logo após a capa |
| `historico` | Arquivo do histórico e por quanto tempo lembrar |

Para ativar a personalização de Cinema, defina `personalizacao_cultural.ativar`
e `personalizacao_cultural.letterboxd.ativar` como `true` e configure
`feed_url` com a URL RSS do seu perfil. Por padrão são considerados os filmes
assistidos nos últimos 7 dias, ordenados por nota e depois pela data assistida.
Os artigos relacionados respeitam o histórico e o filtro ORES; se não houver
uma relação elegível ou o feed falhar, o sorteio normal continua como fallback.

O filtro ORES do sorteio de artigos é configurável em `wikipedia.filtro_qualidade`.
Ele avalia a revisão atual do candidato (classes Stub, Start, C, B, GA e FA) e,
por padrão, aceita B ou superior. Candidatos abaixo do limiar são descartados e
o sorteio tenta outro; se o serviço ORES falhar, o artigo segue pelos critérios
atuais e um aviso é registrado. Use `ativar: false` para desligar o filtro. Se a
opção não estiver configurada, o sorteio mantém o comportamento anterior.

## Automação e entrega

Para rodar toda semana (exemplo: domingos, 7h), use o `cron`:

```cron
0 7 * * 0 cd /caminho/para/jornal-eink && .venv/bin/python main.py
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
  layout.py          # valida fontes e ordena seções configuráveis
  wikipedia.py       # sorteio e limpeza de artigos
  feeds.py           # notícias (RSS/OPML) e DW
  formulas.py        # LaTeX -> MathML
  capa.py            # capa generativa
  epub_builder.py    # montagem do epub
  historico.py       # controle de itens já publicados
docs/TODO.md         # ideias e pendências
```

## Roadmap

Veja [`docs/TODO.md`](docs/TODO.md).

## Créditos e licenças de conteúdo

- Textos e imagens da Wikipédia estão sob [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) e são creditados em cada capítulo.
- Notícias e conteúdo da DW pertencem aos seus respectivos autores; o uso aqui é pessoal, e cada capítulo traz o link da fonte.
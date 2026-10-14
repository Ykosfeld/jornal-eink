# Especificação: priorização cultural (Letterboxd para Cinema, Last.fm para Música)

## Objetivo e escopo

Priorizar artigos da Wikipédia para temas culturais com base na atividade recente do usuário:
- **Cinema**: com base nos filmes assistidos e avaliados no Letterboxd.
- **Música** e **Música clássica**: com base nas músicas, álbuns e artistas mais ouvidos no Last.fm.

A personalização complementa o sorteio existente: se não houver registros
recentes ou candidatos relacionados elegíveis, os temas continuam usando o
mecanismo de sorteio atual.

## Fonte de dados e configuração

- Consultar o feed RSS do perfil Letterboxd configurado.
- Por padrão, considerar filmes assistidos nos últimos **7 dias**; a janela
  deve ser configurável.
- Preferir configurar a URL completa do feed RSS para não depender de
  inferências sobre o nome de usuário.
- A integração é opt-in. Configuração ausente ou desativada não altera o
  comportamento atual.
- Configuração inválida, como uma janela não positiva ou uma URL que não seja
  HTTP(S), deve gerar erro explícito, seguindo o padrão de validação do
  projeto.

## Parsing e seleção dos filmes

- Usar `letterboxd:watchedDate` como data de visualização. Não usar `pubDate`
  para decidir se o filme está na janela: esse campo representa a publicação ou
  registro da atividade no feed.
- Usar `letterboxd:filmTitle` e `letterboxd:filmYear` para identificar o filme,
  e `letterboxd:memberRating` como nota numérica.
- Tolerar namespaces XML e validar que título e data assistida estejam
  presentes e válidos. Dados ausentes ou malformados não devem ser convertidos
  silenciosamente em valores inventados.
- Quando `memberRating` estiver ausente, tratar o filme como sem nota. O feed
  consultado representa avaliações ausentes omitindo esse elemento.
- Descartar registros anteriores à janela configurada. Se não houver filmes
  dentro da janela, não consultar filmes antigos como fallback.
- Ordenar deterministicamente por nota decrescente e, depois, por data
  assistida decrescente. Filmes sem nota ficam abaixo dos avaliados; entre
  filmes sem nota, ordenar pela data assistida mais recente primeiro.
- Ignorar `description` e demais dados pessoais da atividade. Não copiar
  comentários ou resenhas do feed para fixtures, logs ou o epub.
- Falhas de rede, RSS inválido ou perfil sem acesso devem ser reportados sem
  impedir a geração da edição.

## Relações aceitas e priorização

- Favorecer relações diretas e verificáveis, não semelhanças temáticas
  inferidas apenas por palavras em comum.
- Como o feed do Letterboxd fornece os títulos em inglês, a busca consulta
  por padrão a Wikipédia em inglês (`https://en.wikipedia.org/w/api.php`,
  configurável via `letterboxd.wikipedia_api`), gerando o capítulo em inglês
  (`lang="en"`), com candidatos diretos derivados do título e ano
  (ex.: `Film (2006 film)`, `Film (film)` e `Film`).
- Para cada filme, buscar candidatos na Wikipédia; validar o artigo do filme
  por sua infocaixa e examinar somente linhas de crédito explicitamente
  identificadas nela (como direção, roteiro, atuação ou composição da trilha),
  com suporte a infocaixas em inglês (`Template:Infobox film`) e em português
  (`Info/Cinema`). Considerar primeiro o artigo do próprio filme e, em
  seguida, artigos sobre pessoas com crédito direto nele.
- Confirmar relações com dados da Wikipédia ou créditos/metadados confiáveis.
  Não associar um artigo quando a correspondência for ambígua.
- Processar filmes na ordem definida pela nota e data. Se houver mais de um
  candidato para um filme, a relação direta com o próprio filme precede os
  artigos de pessoas creditadas.
- Respeitar o histórico de artigos já publicados. As categorias configuradas
  continuam dirigindo o sorteio aleatório de Cinema usado como fallback; os
  candidatos personalizados são classificados pela correspondência verificada
  ao filme/crédito e pelo filtro ORES/Lift Wing.
- Marcar no capítulo selecionado por Letterboxd, no campo de nota já usado pelo
  jornal, a mensagem humorística: “Um passarinho azul, verde e laranja me
  contou que você ia gostar.”
- Se nenhum candidato relacionado puder ser encontrado, for confirmado ou
  elegível, recorrer ao sorteio atual de Cinema.

## Qualidade dos artigos

- Avaliar cada candidato relacionado pelo filtro de qualidade (Lift Wing),
  usando o modelo adequado para o idioma do artigo (`enwiki-articlequality`
  para artigos da Wikipédia em inglês, e `ptwiki-articlequality` para português),
  respeitando `wikipedia.filtro_qualidade` (classe mínima configurada).
- Rejeitar candidatos abaixo do limite e tentar o próximo candidato conforme
  a ordem de prioridade.
- Se não restar candidato relacionado elegível, usar o sorteio atual, que
  também deve respeitar o filtro ORES/Lift Wing configurado.
- Preservar o comportamento existente em caso de indisponibilidade do modelo:
  registrar aviso e não rejeitar um candidato apenas por essa falha.

## Configuração proposta

Adicionar à seção `personalizacao_cultural` do `config.yaml` as configurações de Letterboxd e Last.fm:

```yaml
personalizacao_cultural:
  ativar: false
  letterboxd:
    ativar: false
    feed_url: ""
    janela_dias: 7
    max_filmes: 7
    max_creditos_por_filme: 5
  lastfm:
    ativar: false
    usuario: ""
    api_key: ""                   # ou via variável de ambiente LASTFM_API_KEY
    janela_dias: 7
    max_itens: 10
    temas:
      - Música
      - Música clássica
```

- A ausência ou desativação de cada serviço mantém a seleção padrão de sorteio.
- `janela_dias` e limites de itens devem ser inteiros positivos.
- Para o Last.fm, a consulta utiliza a API oficial (`user.getrecenttracks`), selecionando os mais ouvidos com desempate por recência, e avalia candidatos bilíngues (pt/en) equilibrando qualidade (Lift Wing) e tamanho em caracteres.

## Privacidade e persistência

- Usar os dados dos filmes somente em memória durante a geração da edição.
- Não persistir a lista consultada no histórico ou relatório.
- Não registrar URLs privadas, resenhas ou comentários do feed em logs ou no
  epub. O artigo selecionado continua tendo as informações de fonte e crédito
  que o projeto já publica.

## Compatibilidade

- Com a integração desativada, a seleção permanece idêntica ao comportamento
  existente, inclusive reprodutibilidade via `--semente`.
- Não alterar os temas Música, Música clássica, notícias, DW, escolhas do
  editor ou outros temas.
- A personalização não deve ser tratada como sucesso quando a consulta falhar:
  informar a falha e seguir com o sorteio atual.

## Critérios de aceitação

1. Com Letterboxd habilitado, ler o feed configurado e considerar apenas
   entradas cuja `watchedDate` esteja dentro da janela configurada (7 dias por
   padrão).
2. Ordenar por nota decrescente e, em empate, por data assistida decrescente;
   entradas sem nota ficam depois das avaliadas.
3. Sem filmes recentes, não usar filmes antigos como prioridade e manter o
   sorteio existente para Cinema.
4. Relações diretas devem ser verificadas; relações ambíguas não podem
   influenciar a seleção.
5. Candidatos relacionados reprovados pelo ORES não são publicados enquanto
   houver outros candidatos elegíveis; se não houver, usar o sorteio atual.
6. Feed indisponível ou inválido deve gerar aviso e não impedir a edição.
7. A integração desativada deve preservar o resultado do sorteio atual.
8. Testes automatizados devem cobrir parsing RSS usando namespaces, datas,
   notas presentes/ausentes, janela temporal, ordenação, duplicatas, erros de
   feed, correspondências, ORES, fallback e ausência de persistência dos dados
   consumidos.

## Pontos a resolver durante a implementação

- O limite de filmes e créditos por filme restringe as consultas à Wikipédia;
  se os candidatos encontrados não forem elegíveis, recorrer ao sorteio.
- Usar fixtures RSS sintéticas com a mesma estrutura observada no feed real;
  não armazenar nele resenhas, comentários ou outros dados pessoais.

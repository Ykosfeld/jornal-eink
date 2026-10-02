# Especificação: priorização de artigos de Cinema pelo Letterboxd

## Objetivo e escopo

Priorizar artigos da Wikipédia para o tema **Cinema** com base nos filmes que
o usuário assistiu nos últimos dias e registrou no Letterboxd. Esta etapa
implementa somente a integração com Letterboxd. A seleção dos temas **Música**
e **Música clássica** permanece inalterada; a integração Last.fm fica para uma
etapa futura, registrada em [TODO.md](./TODO.md).

A personalização complementa o sorteio existente: se não houver filmes
recentes ou candidatos relacionados elegíveis, Cinema continua usando o
mecanismo atual.

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
- Para cada filme, buscar candidatos na Wikipédia; validar o artigo do filme
  por sua infocaixa e examinar somente linhas de crédito explicitamente
  identificadas nela. Considerar primeiro o artigo do próprio filme e, em
  seguida, artigos sobre pessoas com crédito direto nele, como direção,
  roteiro, atuação ou composição da trilha.
- Confirmar relações com dados da Wikipédia ou créditos/metadados confiáveis.
  Não associar um artigo quando a correspondência for ambígua.
- Processar filmes na ordem definida pela nota e data. Se houver mais de um
  candidato para um filme, a relação direta com o próprio filme precede os
  artigos de pessoas creditadas.
- Respeitar o histórico de artigos já publicados. As categorias configuradas
  continuam dirigindo o sorteio aleatório de Cinema usado como fallback; os
  candidatos personalizados são classificados pela correspondência verificada
  ao filme/crédito e pelo filtro ORES.
- Marcar no capítulo selecionado por Letterboxd, no campo de nota já usado pelo
  jornal, a mensagem humorística: “Um passarinho azul, verde e laranja me
  contou que você ia gostar.”
- Se nenhum candidato relacionado puder ser encontrado, for confirmado ou
  elegível, recorrer ao sorteio atual de Cinema.

## Qualidade dos artigos

- Avaliar cada candidato relacionado pelo filtro ORES existente para a
  Wikipédia em português, usando `wikipedia.filtro_qualidade` (atualmente
  classe mínima **B**).
- Rejeitar candidatos abaixo do limite e tentar o próximo candidato conforme
  a ordem de prioridade.
- Se não restar candidato relacionado elegível, usar o sorteio atual, que
  também deve respeitar o filtro ORES configurado.
- Preservar o comportamento existente em caso de indisponibilidade do ORES:
  registrar aviso e não rejeitar um candidato apenas por essa falha.

## Configuração proposta

Adicionar uma seção opcional `personalizacao_cultural` ao `config.yaml`, com
valores equivalentes a:

```yaml
personalizacao_cultural:
  ativar: false
  letterboxd:
    ativar: false
    feed_url: ""
    janela_dias: 7
    max_filmes: 7
    max_creditos_por_filme: 5
```

- A ausência ou desativação da seção mantém a seleção atual.
- `janela_dias` deve ser um inteiro positivo.
- `max_filmes` limita quantos filmes ordenados são processados (7 por padrão);
  `max_creditos_por_filme` limita quantos links de crédito são consultados por
  filme (5 por padrão).
- Não adicionar configuração Last.fm nesta etapa.

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

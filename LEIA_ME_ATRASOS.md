# J2I MES — Saldo em atraso por equipamento

Atualização cumulativa: inclui o encerramento total/parcial entregue anteriormente e acrescenta a nova consulta.

## Onde acessar

Menu Desempenho Industrial → Saldo em atraso por equipamento.

Acesso com o mesmo login administrativo já exigido para Desempenho Industrial. A tela é somente de consulta: não muda OPs, datas, métricas, estoque ou apontamentos.

## Regra do atraso

Entram passagens programadas para uma data anterior à data atual do servidor, ou seja, até ontem inclusive. Não há limite inicial: toda a carteira vencida é considerada.

A posição é o saldo ATUAL dessas passagens, e não uma fotografia histórica do fechamento de ontem. Produção apontada hoje reduz o saldo; uma passagem integralmente concluída hoje deixa de aparecer. A data do corte e a hora da consulta aparecem no topo. O botão Atualizar saldos recalcula a posição.

Exemplo em 28/10: etapa prevista para 27/10, com 100 peças, das quais 40 já foram apontadas, entra com 60 peças de saldo. Se o fator da métrica preservada for 0,8 m²/peça, o atraso será 48 m². Etapas previstas para 28/10 ou depois ficam fora.

## Cálculo

- Não iniciada: usa a quantidade programada, descontando sucata já registrada nas passagens anteriores da mesma OP/lote.
- Em andamento: considera o saldo ainda não encerrado nessa passagem. Peças produzidas fisicamente mas ainda não apontadas não podem ser descontadas automaticamente.
- Parcial encerrada: soma as sessões encerradas e mantém apenas o saldo a retomar. Uma reabertura não duplica o saldo.
- Concluída integralmente: não entra.
- Passagem já iniciada: preserva o saldo de entrada congelado, inclusive se o lote estiver em sequência livre.
- Etapas bloqueadas por processos anteriores também representam trabalho pendente e entram quando vencidas.
- Passagens repetidas do mesmo equipamento são trabalhos distintos: entram separadamente e somam sua carga; a quantidade de OPs usa contagem distinta por equipamento/unidade.

Conversão: saldo em peças × fator da métrica. Para passagens iniciadas, usa a métrica preservada no primeiro apontamento; para não iniciadas, a regra preservada na programação. São respeitados área, medidas lineares, peças, bordas, multiplicadores e unidade personalizada. Alterar o cadastro atual não recalcula o histórico silenciosamente.

Se um equipamento tiver passagens com unidades diferentes, elas aparecem em linhas separadas. Não existe total geral somando m², metros e peças. Os equipamentos inativos com saldo também aparecem, identificados como Inativo.

## Informações da tela

Resumo: código, equipamento, setor, situação do cadastro, unidade, total em atraso, quantidade de OPs distintas, passagens pendentes, maior atraso em dias corridos e pendências de cálculo.

Filtros: setor, equipamento e mostrar somente equipamentos com pendências. Desmarque a última opção para ver também os equipamentos sem saldo vencido.

Detalhamento: OP, lote, passagem, peça, data prevista, dias de atraso, situação, saldo em peças, saldo na métrica e eventuais pendências. CSVs do resumo e do detalhamento respeitam os filtros.

Medidas inválidas ou fatores zero não são apresentados como atraso zero: o total correspondente fica indisponível e os detalhes indicam a pendência. O CSV de resumo também informa o subtotal que pôde ser calculado. Registros sem data/programação válida têm aviso, pois não se presume quando venceram.

## Instalação no servidor Windows

1. Extraia o ZIP em uma pasta separada, por exemplo C:\J2I_ATUALIZACAO_ATRASOS.
2. Pare o MES/Streamlit, API e alimentadores, evitando apontamentos durante a troca.
3. Abra o PowerShell dentro da pasta app extraída, onde está atualizar_mes.py.
4. Execute:

```powershell
py -3.11 atualizar_mes.py --destino "C:\J2I_SERVER\apps\j2i_mes\app" --servidor-parado
```

5. Aguarde a confirmação de atualização e anote o caminho do backup.
6. Reinicie com o procedimento habitual e atualize o navegador. O novo item estará dentro de Desempenho Industrial.

O atualizador preserva os bancos, planilha, credenciais e configuração do servidor. Faz backup dos códigos substituídos, bancos locais pela API SQLite e Excel local antes da troca. Se os dados estiverem configurados em outros caminhos, faça também backup desses caminhos. Não é preciso mudar portas ou Cloudflare. Não houve nova dependência.

Se a atualização de parciais ainda não foi instalada, este pacote também a instala. Leia LEIA_ME_PARCIAIS.md sobre seu funcionamento e sobre as limitações de retorno à versão antiga após usar parciais.

## Validação

Testes automatizados em SQLite temporário: corte até ontem, saldo de OP não iniciada, apontamento feito hoje, parcial, reabertura sem duplicação, sucata anterior, área, comprimento, passagens repetidas, unidades separadas, regra preservada, medida inválida, data inválida, falta de programação, equipamento inativo e sequência livre. Inclui os testes de regressão do encerramento parcial.

Para repetir na pasta app:

```powershell
py -3.11 -m unittest discover -s tests -v
py -3.11 tests\verificar_interface_atrasos.py
```

O segundo comando usa Streamlit AppTest. Os testes usam dados fictícios isolados. A instalação no Windows e a conferência dos totais com OPs reais ainda precisam ser feitas no seu ambiente. Esta entrega não alterou seu servidor em execução.

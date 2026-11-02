# J2I MES — Correção das coladeiras, conferida em 28/10/2026

## Diagnóstico confirmado na cópia recebida

O banco passou no PRAGMA quick_check. A coladeira 126 já não tem programação em peças nas datas conferidas. A coladeira 122 ainda tem seis passagens (duas por OP) em peças, embora a métrica atual e a meta sejam em metros lineares.

| Lote | OP | Passagens | Quantidade por passagem | Medida oficial na ficha | Total das duas passagens após correção |
|---|---|---|---:|---|---:|
| 10670 | 01323511 | 5 e 6 | 16 | 0,730/0,120/0,015 m | 23,360 m linear |
| 10698 | 01327856 | 5 e 6 | 300 | 0,730/0,120/0,015 m | 438,000 m linear |
| 10698 | 01327857 | 5 e 6 | 12 | 0,730/0,120/0,015 m | 17,520 m linear |

Os PDFs confirmam duas passagens de comprimento na coladeira 122, ambas com fator 0,730 m/peça. Não se duplica o ordinal “2º” dentro de uma passagem: a segunda passagem já tem seu registro próprio.

Havia apontamentos nas OPs em outros equipamentos: código 96 para as OPs 01327856/01327857 e código 54 para a OP 01323511. Nenhuma das seis passagens da coladeira 122 tinha sido iniciada na cópia enviada. A função antiga bloqueava a OP inteira por existir qualquer apontamento; isso impedia a correção dessas passagens futuras.

Após o reparo testado, o total da coladeira 122 ficou em 56,080 m linear em 30/10 e 455,520 m linear em 03/11. O total de 30/10 inclui outras OPs já convertidas anteriormente. A coladeira 126 permaneceu em 51,480 m linear em 30/10 e 4,300 m linear em 03/11. Estes valores se referem à cópia enviada, não a novos dados inseridos depois dela.

## O que este pacote corrige

1. Reaplicar métrica passa a preservar somente as passagens já iniciadas. Uma passagem futura pode receber a métrica correta mesmo quando a OP já teve trabalho em outro equipamento.
2. Em OPs já iniciadas, a reaplicação preserva integralmente consumos, política de baixa, estoque e apontamentos. Em OPs sem nenhum apontamento, mantém o recálculo de consumo previsto já existente no sistema.
3. Acrescenta um reparo específico para as seis passagens da tabela. Esse reparo altera somente regra_json e versão em mes_programacao e registra uma auditoria. Não modifica quantidade, data, medida, produção, catálogo, consumos nem estoque.
4. Programação diária × meta agora lista as OPs, passagens, medidas e datas responsáveis por “Dimensão pendente”, com exportação em CSV.
5. Mantém as melhorias anteriores: parciais, atraso por equipamento e Programado × realizado.

## Instalação e aplicação no servidor

Não substitua seu banco pelo arquivo enviado nesta conversa: o servidor pode ter recebido novos apontamentos. Este pacote não contém banco de produção.

1. Extraia o ZIP em uma pasta separada do servidor.
2. Pare MES/Streamlit, API e alimentadores para a atualização e o reparo.
3. Abra o PowerShell na pasta app extraída, onde estão atualizar_mes.py e corrigir_coladeira_122.py.
4. Atualize o código:

```powershell
py -3.11 atualizar_mes.py --destino "C:\J2I_SERVER\apps\j2i_mes\app" --servidor-parado
```

5. Aplique o reparo nas seis passagens do banco ATUAL:

```powershell
py -3.11 corrigir_coladeira_122.py --banco "C:\J2I_SERVER\apps\j2i_mes\app\apontamentos_operacionais.db" --aplicar --servidor-parado
```

Para apenas consultar previamente, execute o segundo comando sem --aplicar e sem --servidor-parado. Se o banco efetivamente utilizado estiver em outro caminho por configuração PPCP_BANCO_OPERACIONAL, substitua o caminho por esse banco. Use o Python habitual caso não execute com py -3.11.

6. Confirme a mensagem de sucesso e o caminho do backup. Reinicie pelo procedimento habitual e atualize o navegador.
7. Confira as coladeiras 122 e 126 na programação diária de 30/10 a 03/11.

O atualizador faz backup dos arquivos substituídos e dos dados locais. O reparo também faz backup próprio do banco atual pela API SQLite antes de gravar. Ambos mantêm os dados existentes. Se uma das seis passagens tiver começado desde o envio, ou se regra, medida, lote, equipamento ou quantidade divergirem do conferido, o reparo recusa a alteração inteira. Nesse caso, envie a mensagem: não force o reparo. Rodar novamente depois de corrigido não duplica as alterações nem a auditoria.

## Pendência real de dimensões — precisa de informação da fábrica

Estas quatro OPs do lote 10698 têm “Medida: 0,000/0,000/0,000” no próprio PDF. São sete passagens de coladeira na programação de 03/11. Não foram preenchidas automaticamente.

| OP | Página do PDF 10698 | Texto dimensional na descrição da peça (não confirmado como medida operacional) |
|---|---:|---|
| 01327844 | 177 | Frente de gaveta Malaga — 408X204X15 |
| 01327950 | 178 | Lateral direita caixote Malaga — 412X385X15 |
| 01327974 | 179 | Lateral esquerda caixote Malaga — 412X385X15 |
| 01327982 | 180 | Base caixote Malaga — 385X384X15 |

É necessário confirmar comprimento, largura e unidade operacional e corrigir o campo Medida na origem. A descrição é somente uma referência; não substitui confirmação, pois pode conter medida nominal ou orientação diferente da aplicada no processo.

Também há divergência de roteiro: os PDFs novos identificam equipamento 131 nessas passagens, enquanto o banco recebido as programa no equipamento 23. A correção não altera esse destino. Confirme se houve remanejamento intencional de 131 para 23. Na OP 01327844, o PDF repete “COLAR 2ª LARG.” na quarta passagem, apesar da observação “4 LADOS”; confirme o roteiro antes de assumir dois comprimentos e duas larguras.

A tela continuará sinalizando “Dimensão pendente” para essas OPs até existirem medidas válidas. A lista detalhada adicionada torna a origem do aviso visível. A correção das seis passagens da coladeira 122 é independente dessa pendência e pode ser aplicada agora.

## Evidência e validação

Conferência dos PDFs: 10670, página 172; 10698, páginas 207 e 208 para as três OPs de métrica incorreta. Dimensões zeradas conferidas nas páginas 177 a 180 do 10698.

Na cópia do banco real, foram alteradas exatamente seis linhas de mes_programacao e acrescentada uma auditoria. Todas as demais tabelas foram comparadas antes/depois e permaneceram iguais, incluindo ordens_operacionais, mes_resultados, mes_consumos, mes_insumos, mes_movimentos e mes_baixa_unica_op. O arquivo original enviado permaneceu intacto. Backup e repetição sem efeitos adicionais foram verificados.

Testes automatizados do pacote verificam recálculo por passagem, preservação de consumo quando a OP já começou, proteção de passagens abertas/parciais/concluídas, recusa de dados divergentes, prévia obsoleta, repetição do reparo e regressões anteriores. A interface foi conferida com Streamlit AppTest. Não houve execução no seu servidor Windows.

```powershell
py -3.11 -m unittest discover -s tests -v
py -3.11 tests\verificar_interface_coladeiras.py
```

As orientações antigas de LEIA_ME_V6.md que falam em bloqueio da OP inteira para reaplicar métricas são substituídas pelas regras deste documento. As demais proteções de importação, substituição de lote e preparação de consumo continuam vigentes.

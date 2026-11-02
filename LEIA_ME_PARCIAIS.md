# J2I MES — Encerramento total ou parcial por equipamento

Pacote de atualização baseado no j2i_mes.rar enviado nesta conversa. Mantém o projeto existente e acrescenta sessões parciais de produção. Os bancos, Excel, configurações de acesso, senhas, serviços e Cloudflare do servidor não são substituídos pelo atualizador.

## Instalação no Windows

1. Extraia este ZIP em uma pasta separada, por exemplo C:\J2I_ATUALIZACAO_PARCIAIS. Não extraia por cima do aplicativo em execução.
2. Combine a interrupção dos apontamentos. Encerre o MES/Streamlit, API e alimentadores antes de atualizar. Não é necessário encerrar as OPs abertas: seus registros serão preservados.
3. Abra o PowerShell dentro da pasta app extraída (onde está atualizar_mes.py).
4. Execute:

```powershell
py -3.11 atualizar_mes.py --destino "C:\J2I_SERVER\apps\j2i_mes\app" --servidor-parado
```

Se usa outro Python, substitua `py -3.11` pelo executável habitual. O atualizador usa somente bibliotecas padrão. Não houve nova dependência de execução.

5. Aguarde a mensagem de sucesso e anote a pasta de backup apresentada.
6. Reinicie pelo mesmo procedimento que já utiliza no servidor. Não mude portas ou configurações de acesso.
7. Atualize a página dos operadores. A primeira inicialização adiciona a coluna de encerramento parcial e adapta o índice da passagem, preservando os apontamentos existentes.
8. Antes de liberar a equipe, valide em uma cópia isolada do sistema o exemplo abaixo. Não use uma OP de produção para simular quantidades fictícias.

O atualizador faz backup dos códigos substituídos, dos bancos locais pela API SQLite e da planilha local antes da troca. Se os bancos ou Excel estiverem configurados em outros caminhos, faça também backup consistente desses caminhos antes de atualizar. O script não interrompe serviços automaticamente.

## Encerramento individual

- Clique em Finalizar OP.
- Responda “Encerrar esta OP na quantidade total ou parcial?”. A seleção inicial é “Selecione”, para exigir uma escolha explícita.
- Total: encerra todo o saldo disponível nesta sessão. Boas = saldo menos sucata.
- Parcial: informe a quantidade processada nesta sessão, incluindo boas e sucata. Ela deve ser maior que zero e menor que o saldo.
- Informe sucata e retrabalho, quando houver. Retrabalho já está incluído nas boas, não soma peças ao produzido.
- Confirme. A sessão de trabalho termina nesse horário e o equipamento deixa de ter essa sessão aberta.

Exemplo: OP de 100 peças, parcial de 40 (38 boas e 2 de sucata). O saldo é 60. Ao ler novamente a mesma OP no mesmo equipamento, abre uma nova sessão com 60 peças. Se produzir 59 boas e 1 de sucata e escolher Total, a passagem termina; a próxima etapa recebe 97 peças boas.

É possível repetir os parciais em horários ou dias diferentes. Cada sessão tem abertura, fechamento, boas, sucata, retrabalho e duração próprios. O período entre o encerramento parcial e a nova abertura não conta como tempo de produção dessa OP. A reabertura é feita pelo operador, lendo a OP normalmente, inclusive pelo campo de várias OPs.

## Várias OPs

Em “Finalizar várias OPs ao mesmo tempo”, abra o bloco de cada OP, marque “Encerrar esta OP” e escolha Total ou Parcial individualmente. No parcial, preencha a quantidade processada; no total, esse campo é ignorado e o saldo é usado. Sucata, retrabalho e observação também são individuais.

A confirmação é atômica: se qualquer OP selecionada estiver inválida, nenhuma delas é encerrada. Corrija as informações e confirme novamente. As selecionadas usam o mesmo horário de fechamento.

## Saldo, roteiro, métricas e histórico

- Parcial encerra a sessão, mas mantém a passagem pendente. A consulta de OPs pendentes por lote e o sequenciamento incluem seu saldo.
- A reabertura continua na mesma passagem enquanto houver saldo. Não avança para uma segunda passagem da mesma máquina antes da conclusão da primeira.
- No sequenciamento normal, as etapas posteriores aguardam a conclusão integral das anteriores. Lotes já configurados com sequência livre mantêm essa exceção.
- O saldo de uma passagem já iniciada é congelado; não muda silenciosamente se uma etapa anterior terminar depois em um lote de sequência livre.
- A métrica da primeira sessão é reutilizada nas reaberturas. Mudanças no cadastro não recalculam a passagem em execução.
- Os resultados das sessões encerradas somam apenas o produzido de cada sessão. A programação por passagem permanece única em mes_programacao.
- Últimos apontamentos mostra boas, sucata, saldo e distingue sessão parcial encerrada de passagem concluída.
- Registros antigos finalizados permanecem concluídos. Esta atualização não reabre apontamentos antigos já encerrados como totais.

## Estoque

- Por equipamento/etapa: cada sessão baixa a parcela proporcional às peças processadas (boas + sucata).
- Baixa única ao iniciar a OP: mantém a baixa integral única na primeira abertura. Reabrir uma parcial não baixa novamente.
- Baixa única ao finalizar a primeira etapa: aguarda a conclusão de todo o saldo dessa primeira passagem. Encerramentos parciais não antecipam a baixa integral. A última sessão da passagem efetua a baixa uma única vez.
- Falta de saldo com bloqueio ativo cancela a confirmação e deixa a sessão aberta. Dados de produção e estoque permanecem na mesma transação.

## Verificação realizada e limites

Testes com SQLite temporário cobrem parciais sucessivas, dias diferentes, sucata, passagem repetida, bloqueio da etapa seguinte, saldo congelado, estoque proporcional, baixa única, rollback de múltiplas OPs, repetição da migração do índice e concorrência de abertura/fechamento. As funções reais de abertura e fechamento são carregadas sem iniciar o aplicativo inteiro; autenticação web é isolada nos testes.

Teste Streamlit AppTest cobre escolha de parcial individual, reabertura em lote, encerramento misto total/parcial e reabertura individual. Não substitui validação no navegador e no Windows do servidor, nem teste de carga com todos os operadores. A cópia recebida com o servidor em execução não foi considerada um backup validado.

Para executar os testes do pacote, dentro de app:

```powershell
py -3.11 -m unittest discover -s tests -v
py -3.11 tests\verificar_interface.py
```

O segundo comando exige Streamlit instalado. Execute os testes separadamente: eles substituem a integração da sessão web para não depender de login real.

## Retorno à versão anterior

Depois que houver sessões parciais, não reinstale apenas o código antigo: ele não interpreta essas sessões e pode falhar ao recriar o índice anterior. Pare o sistema e avalie uma restauração coordenada de código e banco com o backup pré-atualização, sabendo que isso descarta registros posteriores ao backup. Preserve também uma cópia atual antes de qualquer retorno. Não restaure o banco antigo sobre produção ativa.

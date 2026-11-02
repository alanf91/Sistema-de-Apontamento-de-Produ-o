import argparse,ast,json,hashlib,os
from pathlib import Path
from datetime import datetime

def instalar(destino,parado):
 if not parado:raise ValueError('Pare o MES e use --servidor-parado.')
 src=Path(__file__).resolve().parent;dest=Path(destino)
 m=json.loads((src/'manifesto_oee.json').read_text())
 for n,h in m.items():
  raw=(src/n).read_bytes();ast.parse(raw)
  if hashlib.sha256(raw).hexdigest()!=h['depois']:raise ValueError('Pacote alterado: '+n)
  alvo=dest/n
  if alvo.exists() and hashlib.sha256(alvo.read_bytes()).hexdigest() not in [h['antes'],h['depois']]:raise ValueError('Versão diferente de '+n+'. Envie o arquivo atual para compatibilização.')
  if h['antes'] and not alvo.exists():raise ValueError('Instale primeiro o Resumo Executivo.')
 if '# J2I_DIRETORIA_V1' not in (dest/'J2I_MES.py').read_text(encoding='utf-8-sig'):raise ValueError('Menu Resumo Executivo não instalado.')
 backup=dest/'backups'/('antes_oee_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'));backup.mkdir(parents=True)
 antigos={n:(dest/n).read_bytes() if (dest/n).exists() else None for n in m}
 for n,b in antigos.items():
  if b is not None:(backup/n).write_bytes(b)
 try:
  for n in m:
   tmp=dest/(n+'.tmp');tmp.write_bytes((src/n).read_bytes());os.replace(tmp,dest/n)
 except Exception:
  for n,b in antigos.items():
   if b is None:(dest/n).unlink(missing_ok=True)
   else:(dest/n).write_bytes(b)
  raise
 print(f'Atualizado. Backup: {backup}. Reinicie o MES. Cadastre ritmos ideais em Critérios e configuração do OEE.')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--destino',required=True);p.add_argument('--servidor-parado',action='store_true');a=p.parse_args();instalar(a.destino,a.servidor_parado)

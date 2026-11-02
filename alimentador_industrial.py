"""Abre os alimentadores integrados no MES; usa a mesma base e permissões do servidor."""
import os
import tkinter as tk
from tkinter import messagebox
import webbrowser
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode


def main():
    root=tk.Tk();root.title('J2I — Alimentador Industrial');root.geometry('620x220')
    tk.Label(root,text='Alimentador integrado ao MES 6',font=('Segoe UI',16,'bold')).pack(pady=12)
    tk.Label(root,text='Endereço do MES no servidor (local, rede ou domínio já configurado)').pack()
    url=tk.StringVar(value=os.environ.get('J2I_MES_URL','http://127.0.0.1:8501'))
    tk.Entry(root,textvariable=url,width=75).pack(pady=8)
    def abrir(pagina):
        partes=urlsplit(url.get().strip())
        if partes.scheme not in ('http','https') or not partes.netloc:
            messagebox.showerror('Endereço','Informe um endereço http:// ou https:// válido.');return
        query=dict(parse_qsl(partes.query));query['pagina']=pagina
        webbrowser.open(urlunsplit((partes.scheme,partes.netloc,partes.path,urlencode(query),'')))
    tk.Button(root,text='Importar OPs e programar equipamentos',command=lambda:abrir('importar-lotes')).pack(pady=4)
    tk.Button(root,text='Importar saldo de estoque',command=lambda:abrir('estoque')).pack(pady=4)
    root.mainloop()


if __name__=='__main__':main()

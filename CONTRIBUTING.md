# Como contribuir

Relatos de qualidade são bem-vindos. Informe:

- ID hexadecimal da fala, quando disponível;
- texto aproximado;
- missão, cena ou contexto;
- categoria do defeito: pronúncia, português, pausa, corte, velocidade, ruído,
  duração ou identidade vocal;
- se o problema é reproduzível.

Não envie áudio extraído do jogo, referências privadas, prompts `.pt`, corpus
completo ou arquivos `w3speech` em issues e pull requests.

Mudanças de código devem incluir teste automatizado quando possível. Execute:

```powershell
py -3 -m unittest discover -s tests -v
```


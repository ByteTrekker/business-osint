# business-osint

Graf powiązań polskich firm i osób, budowany wyłącznie na publicznych rejestrach
(KRS, REGON, CEIDG, CRBR, zamówienia publiczne, dotacje UE).

Odpowiada na pytanie, na które wyszukiwarka KRS nie odpowiada:
**„Jak ta firma jest powiązana z innymi firmami i osobami?”**

```
Firma A ──prezes zarządu── Jan Kowalski ──udziałowiec── Firma B
                                                            │
                                                    prezes zarządu
                                                            │
                                                       Anna Nowak ──akcjonariusz── Firma C
```

Projekt w budowie. Fundament — model danych, traversal grafu, API i interfejs —
jest przedmiotem pierwszego pull requesta.

## Licencja

Kod: MIT. Dane pochodzą z rejestrów publicznych i podlegają ich warunkom.

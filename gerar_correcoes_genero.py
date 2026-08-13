#!/usr/bin/env python3
"""Gera correcoes.csv para uma personagem jogavel feminina.

As alteracoes sao feitas por ID e contexto. O programa tambem aprova
explicitamente os falsos positivos sinalizados no manifesto, evitando que o
pipeline fique bloqueado por palavras masculinas referentes a terceiros,
objetos ou expressoes neutras.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path


class CorrectionError(RuntimeError):
    pass


@dataclass
class Decision:
    action: str
    original: str
    final: str
    reason: str
    source_flag: str


def parse_ids(value: str) -> set[str]:
    return {item.lower() for item in value.split() if item.strip()}


BRUXA_IDS = parse_ids("""
0x0002cb65 0x0005a8f2 0x0005b61c 0x0005edc7 0x0005f12d
0x0006019c 0x00062521 0x00067379 0x00069259 0x000692a7
0x0006eb3b 0x0006f87a 0x00070287 0x000711d4 0x00072626
0x000734ce 0x00074718 0x000748d0 0x00077b85 0x0007886d
0x00079b4d 0x00079fb3 0x0007a085 0x0007b994 0x0007df2c
0x00082f54 0x0008580b 0x0008884b 0x00088853 0x0008916b
0x0008ab17 0x000fba7d 0x000fcafd 0x000ff638 0x000ffa2c
0x00101c22 0x00109c96 0x0010c79a 0x0010ca16 0x0010d54b
0x0010de54 0x0010dfd1 0x0010fb8c 0x00110d49 0x00112e9f
0x00113584 0x001136b8 0x00119348 0x0011adf5 0x0011c228
0x0011c529 0x0011c56d 0x0011d3a6 0x0011f4dd 0x0011f7ac
0x0011fc5b 0x0011fc65 0x0011fc69 0x00120937 0x00120f35
0x0012186f 0x001221b1 0x0012511e 0x0012515c 0x0012560b
0x00126029 0x00126031
0x00055633 0x00073de1 0x00073e6c 0x00087b5b 0x00088469
0x0008a3cb 0x0008ee81 0x0010423c 0x0010b4d1 0x0010b5ee
0x0010e543 0x0010f7f9 0x0011053f 0x0011060c 0x0011fc55 0x00121d53
0x00122486 0x0012603e
""")


WORD_GROUPS: dict[tuple[str, str], set[str]] = {
    ("pronto", "pronta"): parse_ids("""
        0x00062d6a 0x00076a28 0x0007b3db 0x0007b5b9 0x0007dcd0
        0x0007de16 0x0007e317 0x0007f393 0x0007f395 0x0007f5f0
        0x0007f746 0x00082221 0x00084602 0x000847b8 0x00084958
        0x0008b145 0x0008cc1c 0x0008d422 0x0008ae4a 0x001023df
        0x00106941 0x0010d7d2 0x00113a25 0x0011c188 0x0011ddf6
    """),
    ("intrigado", "intrigada"): parse_ids("0x0008ae4a"),
    ("sozinho", "sozinha"): parse_ids("""
        0x000601a6 0x0006641e 0x00067349 0x0006750e 0x0006e633
        0x0006ea41 0x0006ea47 0x00072383 0x00073c4c 0x0007ac3c
        0x0008ddf8 0x0009056e 0x00090f04 0x000f4ed7 0x000f6722
        0x000fe420 0x0010643c 0x0010c39f 0x0010cddf 0x0010f76e
        0x0010fe34 0x0011e600 0x0011ed47 0x0011f110 0x0012188d
        0x00126433
    """),
    ("surpreso", "surpresa"): parse_ids("""
        0x0004c6d8 0x000674a9 0x0006f86a 0x0007c6dc 0x0008036d
        0x00087b3a 0x000fc435 0x000fc9f7 0x0010561a 0x00126a6c
    """),
    ("preocupado", "preocupada"): parse_ids("""
        0x0004cbe9 0x00054078 0x0006f385 0x00087aee 0x0008f469
        0x000f6634 0x0011e21a 0x0011e267
    """),
    ("cansado", "cansada"): parse_ids("""
        0x000692ad 0x0007017d 0x000814e6 0x00082584 0x000f6ed8
        0x00104e53 0x0010d13a
    """),
    ("ocupado", "ocupada"): parse_ids("""
        0x0008204e 0x0008225a 0x000f5ffe 0x00115234 0x00118c98
        0x0011ef47 0x0012157d 0x00125d78
    """),
    ("interessado", "interessada"): parse_ids("""
        0x00055666 0x00059596 0x0005fe84 0x00066855 0x00067d83
        0x0006a409 0x00073529 0x00075795 0x0007f577 0x0008a3d5
        0x000f9272 0x000fb2a1 0x000fcada 0x000fd60e 0x00103e87
        0x00105a02 0x0010b2bf 0x0011ae88 0x0011bf69 0x001222a3
    """),
    ("disposto", "disposta"): parse_ids("""
        0x0006cf55 0x0007369c 0x00073e85 0x00075b68 0x000780e2
        0x00083278 0x00083794 0x000863ea 0x0008be95 0x000ff9c9
        0x00100cea 0x00103eaa 0x00105a24 0x0010c3b5 0x0010f7cb
        0x0011c1ea 0x0011f4c2 0x00120457 0x0012150e 0x00122de9
    """),
    ("curioso", "curiosa"): parse_ids("""
        0x00079d97 0x000880f8 0x0008d344 0x00090012 0x00090123
        0x00090385 0x000913f1 0x000f4beb 0x000f7652 0x000f799f
        0x000fe73c 0x0010428f 0x00105a02 0x0010bbca 0x00112906
        0x00113348 0x0011b85e 0x0011c18a 0x0011fc3d 0x00124e1d
        0x001255c5
    """),
    ("velho", "velha"): parse_ids("""
        0x00083ecc 0x0008ca09 0x001008b2 0x0010717c 0x0010719a
    """),
    ("confuso", "confusa"): parse_ids("0x000569ad 0x00125753"),
    ("enganado", "enganada"): parse_ids(
        "0x00059eed 0x00079feb 0x00080179 0x000f94ce 0x00125673"
    ),
    ("furioso", "furiosa"): parse_ids("0x00061e77 0x0007017d"),
    ("nomeado", "nomeada"): parse_ids("0x0006f4bd"),
    ("morto", "morta"): parse_ids("0x0007ca29 0x0010c5c2 0x0010d1e4 0x0010f85c"),
    ("esquartejado", "esquartejada"): parse_ids("0x0010c5c2"),
    ("vivo", "viva"): parse_ids("0x0010f85c"),
    ("satisfeito", "satisfeita"): parse_ids("0x000fe922"),
    ("preparado", "preparada"): parse_ids("0x000feee3"),
    ("nervoso", "nervosa"): parse_ids("0x000692ad 0x00106ec7 0x0010e8a4"),
    ("sóbrio", "sóbria"): parse_ids("0x0010ba27"),
    ("chocado", "chocada"): parse_ids("0x0010bf61"),
    ("derrotado", "derrotada"): parse_ids("0x0010c26d"),
    ("vestido", "vestida"): parse_ids("0x0010d825"),
    ("sujeito", "sujeita"): parse_ids("0x0010e43a"),
    ("tolo", "tola"): parse_ids("0x0010c2dc 0x0010e4c6"),
    ("criterioso", "criteriosa"): parse_ids("0x0011004a"),
    ("astuto", "astuta"): parse_ids("0x00111b8f"),
    ("ansioso", "ansiosa"): parse_ids("0x0011b186"),
    ("discreto", "discreta"): parse_ids("0x0011b671"),
    ("classificado", "classificada"): parse_ids("0x0011c56d"),
    ("preso", "presa"): parse_ids("0x0011da95"),
    ("forasteiro", "forasteira"): parse_ids("0x00090f90 0x000f7c9c 0x0011e6e1"),
    ("andarilho", "andarilha"): parse_ids("0x000f7c9c"),
    ("jogado", "jogada"): parse_ids("0x0011f398"),
    ("puxado", "puxada"): parse_ids("0x0011f60f"),
    ("fascinado", "fascinada"): parse_ids("0x0011fbd5"),
    ("levado", "levada"): parse_ids("0x00121a1b"),
    ("convidado", "convidada"): parse_ids("0x00122de9"),
    ("inteiro", "inteira"): parse_ids("0x001241c4"),
    ("chegado", "chegada"): parse_ids("0x001242a6"),
    ("acostumado", "acostumada"): parse_ids("0x0007034b 0x00124c94"),
    ("caçado", "caçada"): parse_ids("0x00124c94"),
    ("atrasado", "atrasada"): parse_ids("0x001270de"),
    ("aliviado", "aliviada"): parse_ids("0x0007237d"),
    ("perdido", "perdida"): parse_ids("0x000691fb"),
    ("convencido", "convencida"): parse_ids("0x00078ee1"),
    ("certo", "certa"): parse_ids("0x00077582 0x0007c726 0x000fe070"),
    ("errado", "errada"): parse_ids("0x0005c852 0x000f8a79 0x0011bec1"),
    ("fraco", "fraca"): parse_ids("0x00059cdc"),
    ("culpado", "culpada"): parse_ids("0x00090f90"),
    ("conhecido", "conhecida"): parse_ids("0x000553be"),
    ("cego", "cega"): parse_ids("0x000577fa"),
    ("novo", "nova"): parse_ids("0x000658c7"),
    ("bom", "boa"): parse_ids("""
        0x00068364 0x0006d28f 0x00083764 0x0008bd63 0x000f5c2c
        0x001131fd
    """),
    ("ganancioso", "gananciosa"): parse_ids("0x000683a2"),
    ("inimigo", "inimiga"): parse_ids("0x00082384"),
    ("bárbaro", "bárbara"): parse_ids("0x0008b03f"),
    ("aluno", "aluna"): parse_ids("0x000918d6"),
    ("digno", "digna"): parse_ids("0x000f5682"),
    ("bandido", "bandida"): parse_ids("0x000fa495"),
    ("assassino", "assassina"): parse_ids("0x0010a975"),
    ("amigo", "amiga"): parse_ids("0x0010c59a"),
    ("criado", "criada"): parse_ids("0x00104558"),
    ("sortudo", "sortuda"): parse_ids("0x0010f847"),
    ("habilidoso", "habilidosa"): parse_ids("0x00110ee1"),
    ("armado", "armada"): parse_ids("0x00122486"),
}


PHRASE_EDITS: dict[str, list[tuple[str, str]]] = {
    "0x0002aeec": [("um amigo", "uma amiga")],
    "0x0002b302": [("um amigo", "uma amiga")],
    "0x0002af36": [("o instrutor", "a instrutora")],
    "0x0002cac5": [("o seu instrutor", "a sua instrutora")],
    "0x00059cdc": [("Não sou ator", "Não sou atriz")],
    "0x0005c98b": [("um dos seus capachos", "uma das suas capangas")],
    "0x0005a1df": [("muito bom de papo", "muito boa de papo")],
    "0x00060985": [("um carrasco", "uma carrasca")],
    "0x00063b27": [("um traficante de escravos", "uma traficante de escravos")],
    "0x00066412": [("o cozinheiro novo", "a cozinheira nova")],
    "0x0006a24b": [("um dúplice", "uma dúplice")],
    "0x0006f4bd": [("cavaleiro", "cavaleira")],
    "0x00074718": [("não um caçador de bruxas", "não uma caçadora de bruxas")],
    "0x00074680": [("um bandido", "uma bandida")],
    "0x0007533b": [("um ladrão", "uma ladra")],
    "0x00073feb": [("um velho amigo", "uma velha amiga")],
    "0x00076e90": [("o protagonista", "a protagonista")],
    "0x000748d1": [("Um viajante", "Uma viajante")],
    "0x00078f1d": [("pau-mandado", "pau-mandada")],
    "0x00079fb3": [("um cavaleiro errante", "uma cavaleira errante")],
    "0x00082f54": [("um mera bruxa", "uma mera bruxa")],
    "0x00081514": [
        ("nem guarda-costas, nem assassino de aluguel", "nem guarda-costas, nem assassina de aluguel")
    ],
    "0x00082384": [("seu inimiga", "sua inimiga")],
    "0x00082d3d": [
        ("não sou seu soldado, pajem ou cão", "não sou sua soldada, pajem ou cadela")
    ],
    "0x00083064": [("Um amigo preocupado", "Uma amiga preocupada")],
    "0x000842bd": [("o cobrador", "a cobradora")],
    "0x00088f7a": [("Sou o segundo", "Sou a segunda")],
    "0x0008884b": [("um simples bruxa", "uma simples bruxa")],
    "0x0008ab17": [("um gigolô", "uma acompanhante")],
    "0x0008ca07": [("um bruxo irritado", "uma bruxa irritada")],
    "0x0008fa4e": [("seu menino de recados", "sua menina de recados")],
    "0x0008b03f": [("um bárbara", "uma bárbara")],
    "0x000918d6": [("seu aluna", "sua aluna")],
    "0x00090f90": [("um forasteira", "uma forasteira")],
    "0x000f56d7": [("Sou o único", "Sou a única")],
    "0x000f5682": [("qualquer um", "qualquer pessoa")],
    "0x000f6155": [("um ótimo destilador", "uma ótima destiladora")],
    "0x000f7cc8": [("um homem", "uma mulher")],
    "0x000fa495": [("o bandida", "a bandida")],
    "0x000fd5c8": [("um especialista", "uma especialista")],
    "0x000fb2b7": [("um homem feliz", "uma mulher feliz")],
    "0x00100bee": [("assassino", "assassina")],
    "0x00103aa4": [("Não sou um demônio", "Não sou uma criatura demoníaca")],
    "0x00103ddc": [("um regicida", "uma regicida")],
    "0x00103eeb": [("um profissional", "uma profissional")],
    "0x00104558": [("seu criada", "sua criada")],
    "0x00104b64": [
        ("Eu não sou um dos seus soldados", "Eu não faço parte dos seus soldados")
    ],
    "0x00101c22": [("um guarda-costas", "uma guarda-costas")],
    "0x0010a32e": [("esse bruxo está ocupado", "essa bruxa está ocupada")],
    "0x0010c62a": [("nenhum capanga", "nenhuma capanga")],
    "0x0010c79a": [("esse sou eu", "essa sou eu")],
    "0x0010f7f9": [("esse tal bruxa é chato", "essa tal bruxa é chata")],
    "0x0010ca16": [("um negociador", "uma negociadora")],
    "0x0010e1d5": [("me fez herói", "me fez heroína")],
    "0x00112685": [("sou ladrão", "sou ladra")],
    "0x0011a6f5": [("um humano", "uma humana")],
    "0x0011301e": [("todinho seu", "todinha sua")],
    "0x00113584": [("assassino de humanos", "assassina de humanos")],
    "0x001136b8": [("um \"mutante\"", "uma \"mutante\"")],
    "0x00113dce": [("um homem com minha perícia", "uma mulher com minha perícia")],
    "0x0011418a": [("um dos participantes", "uma das participantes")],
    "0x00118cd3": [("o imbecil", "a imbecil")],
    "0x00119d85": [("um matador", "uma matadora")],
    "0x0011c353": [("sou cara doido e imprevisível", "sou uma mulher doida e imprevisível")],
    "0x0011d3a6": [("sou bandido", "sou bandida")],
    "0x0011e6e1": [("um forasteira", "uma forasteira")],
    "0x0011f645": [("um prisioneiro", "uma prisioneira")],
    "0x0012004e": [("o homem que", "a mulher que")],
    "0x001200e6": [("seu chefe", "sua chefe")],
    "0x00120345": [
        ("não sou o seu típico cavalheiro abastado", "não sou a sua típica dama abastada")
    ],
    "0x001221b1": [("um milagreiro", "uma milagreira")],
    "0x00122b2e": [("um especialista", "uma especialista")],
    "0x00122de9": [("seu convidada", "sua convidada")],
    "0x00125090": [("um homem caçado", "uma mulher caçada")],
    "0x0012515c": [("sou herói", "sou heroína")],
    "0x00126029": [("um especialista", "uma especialista")],
    "0x0012602d": [("um connoisseur", "uma conhecedora")],
    "0x0010fdf0": [("Nenhum homem presente", "Nenhuma mulher presente")],
}


SAME_IDS = parse_ids("""
0x00062f45 0x00087c66 0x000f4a95 0x000f6be2 0x000fcaad
0x001036e9 0x001136d4 0x00118fea 0x0011ef7f
""")


SPECIAL_PHRASE_EDITS = {
    "0x0011b142": [("Estou pronto", "Estou pronta")],
    "0x000743ed": [("sou todo ouvidos", "sou toda ouvidos")],
    "0x00079df9": [("Sou todo ouvidos", "Sou toda ouvidos")],
    "0x0007a01e": [("Sou todo ouvidos", "Sou toda ouvidos")],
    "0x000fb8e4": [("Sou todo ouvidos", "Sou toda ouvidos")],
    "0x00110b44": [("sou todo seu", "sou toda sua")],
    "0x0011bea9": [("sou todo ouvidos", "sou toda ouvidos")],
    "0x00123fd7": [("Sou todo ouvidos", "Sou toda ouvidos")],
}


def replace_word(text: str, old: str, new: str) -> tuple[str, bool]:
    pattern = re.compile(rf"\b{re.escape(old)}\b", re.IGNORECASE)

    def repl(match: re.Match[str]) -> str:
        token = match.group(0)
        if token.isupper():
            return new.upper()
        if token[:1].isupper():
            return new[:1].upper() + new[1:]
        return new

    result, count = pattern.subn(repl, text)
    return result, count > 0


def apply_edit(ident: str, text: str) -> tuple[str, list[str]]:
    edited = text
    notes: list[str] = []

    if re.search(r"\bobrigado\b", edited, re.IGNORECASE):
        edited, changed = replace_word(edited, "obrigado", "obrigada")
        if changed:
            notes.append("obrigado→obrigada")

    if ident in BRUXA_IDS:
        for old, new in [
            ("Um bruxo", "Uma bruxa"),
            ("um bruxo", "uma bruxa"),
            ("O bruxo", "A bruxa"),
            ("o bruxo", "a bruxa"),
            ("Do bruxo", "Da bruxa"),
            ("do bruxo", "da bruxa"),
            ("bruxo", "bruxa"),
        ]:
            if old in edited:
                edited = edited.replace(old, new)
        notes.append("bruxo→bruxa (autorreferência)")

    for (old, new), ids in WORD_GROUPS.items():
        if ident in ids:
            edited, changed = replace_word(edited, old, new)
            if not changed:
                raise CorrectionError(f"{ident}: termo esperado ausente: {old!r}")
            notes.append(f"{old}→{new}")

    if ident in SAME_IDS:
        pattern = re.compile(r"\b(?:eu\s+mesmo|mim\s+mesmo)\b", re.IGNORECASE)
        if not pattern.search(edited):
            # 'Sou eu mesmo' também casa em 'eu mesmo'.
            raise CorrectionError(f"{ident}: autorreferência 'mesmo' esperada")
        edited, changed = replace_word(edited, "mesmo", "mesma")
        if changed:
            notes.append("mesmo→mesma (autorreferência)")

    for old, new in PHRASE_EDITS.get(ident, []):
        if old not in edited:
            raise CorrectionError(f"{ident}: trecho esperado ausente: {old!r}")
        edited = edited.replace(old, new)
        notes.append(f"{old}→{new}")

    for old, new in SPECIAL_PHRASE_EDITS.get(ident, []):
        if old not in edited:
            raise CorrectionError(f"{ident}: trecho esperado ausente: {old!r}")
        edited = edited.replace(old, new)
        notes.append(f"{old}→{new}")

    return edited, notes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit-json", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    with args.manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        required = {"id_hex", "acao", "texto_original", "texto_final", "revisar", "detalhe"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise CorrectionError("manifesto com cabeçalho incompatível")
        rows = list(reader)

    by_id = {row["id_hex"].lower(): row for row in rows}
    if len(by_id) != len(rows):
        raise CorrectionError("manifesto possui IDs duplicados")

    expected_ids = set().union(BRUXA_IDS, SAME_IDS, SPECIAL_PHRASE_EDITS, PHRASE_EDITS)
    for ids in WORD_GROUPS.values():
        expected_ids.update(ids)
    missing = sorted(expected_ids - set(by_id))
    if missing:
        raise CorrectionError("IDs de edição ausentes: " + ", ".join(missing[:10]))

    decisions: dict[str, Decision] = {}
    review_ids = {row["id_hex"].lower() for row in rows if row["revisar"]}
    candidate_ids = review_ids | expected_ids

    for ident in sorted(candidate_ids, key=lambda value: int(value, 0)):
        row = by_id[ident]
        original = row["texto_final"]
        final, notes = apply_edit(ident, original)
        if ident == "0x0006c74d":
            reason = "Marcação *eu* confirmada como fala; somente os asteriscos foram removidos."
        elif final != original:
            reason = "Concordância feminina da personagem jogável: " + "; ".join(notes) + "."
        else:
            reason = "Aprovado sem alteração: termo não se refere à personagem jogável."
        decisions[ident] = Decision("gerar", original, final, reason, row["revisar"])

    # O único ID do corpus que não existe nos pacotes oficiais 4.04.
    absent_id = "0x0006823c"
    row = by_id.get(absent_id)
    if row is None:
        raise CorrectionError(f"ID esperado ausente do manifesto: {absent_id}")
    decisions[absent_id] = Decision(
        "usar_original",
        row["texto_final"],
        "",
        "ID ausente dos pacotes oficiais do jogo 4.04.",
        row["revisar"],
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";", lineterminator="\n")
        writer.writerow(["id_hex", "acao", "texto", "motivo"])
        for ident, decision in sorted(decisions.items(), key=lambda item: int(item[0], 0)):
            writer.writerow([ident, decision.action, decision.final, decision.reason])

    audit = []
    for ident, decision in sorted(decisions.items(), key=lambda item: int(item[0], 0)):
        if decision.action == "usar_original":
            classification = "usar_original"
        elif decision.final != decision.original:
            classification = "corrigido"
        else:
            classification = "aprovado_sem_alteracao"
        audit.append({
            "id_hex": ident,
            "classificacao": classification,
            "acao": decision.action,
            "texto_original": decision.original,
            "texto_final": decision.final,
            "motivo": decision.reason,
            "sinalizacao_original": decision.source_flag,
        })

    if args.audit_json:
        args.audit_json.parent.mkdir(parents=True, exist_ok=True)
        args.audit_json.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")

    flagged_covered = sum(ident in decisions for ident in review_ids)
    changed = sum(item["classificacao"] == "corrigido" for item in audit)
    approved = sum(item["classificacao"] == "aprovado_sem_alteracao" for item in audit)
    print(f"Sinalizações cobertas: {flagged_covered}/{len(review_ids)}")
    print(f"Correções femininas: {changed}; falsos positivos aprovados: {approved}")
    print(f"Linhas em correcoes.csv: {len(audit)}")
    print(f"Arquivo: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

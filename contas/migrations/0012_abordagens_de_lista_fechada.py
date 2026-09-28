"""ADR-107: abordagens e áreas voltam a ser lista fechada, guardadas como código.

A ordem importa. As colunas de texto para "Outra" entram **antes** da conversão, senão o que não bate com nenhum
código não teria onde ser guardado e seria simplesmente apagado. Ninguém perde o que escreveu: o que o catálogo
reconhece vira código, e o que não reconhece vira OUTRA mais o texto original, preservado como veio.

A conversão é reversível no sentido que importa: `para_tras` devolve os rótulos por extenso, que é o formato que
a 0009 deixou. Não devolve a grafia exata de quem escrevia errado — e é justamente isso que se queria corrigir.
"""

from django.db import migrations, models

from contas.abordagens import OUTRA, ROTULO_DA_ABORDAGEM, ROTULO_DA_AREA, codigo_da_abordagem, codigo_da_area


def _converter(linhas, para_codigo):
    """(códigos sem repetir, texto do que não foi reconhecido) a partir do que estava escrito à mão."""
    codigos, sobras = [], []
    for texto in linhas or []:
        codigo = para_codigo(texto)
        if codigo and codigo not in codigos:
            codigos.append(codigo)
        elif not codigo:
            limpo = " ".join(str(texto).split())
            if limpo and limpo not in sobras:
                sobras.append(limpo)
    escrito = ", ".join(sobras)[:120]
    if escrito:
        codigos.append(OUTRA)
    return codigos, escrito


def para_frente(apps, schema_editor):
    Psicologo = apps.get_model("contas", "Psicologo")
    # `objects` aqui é o manager puro da migração, sem o filtro de tenant: a conversão é de todas as contas.
    for psicologo in Psicologo.objects.all().iterator():
        psicologo.abordagens, psicologo.abordagem_outra = _converter(psicologo.abordagens, codigo_da_abordagem)
        psicologo.outras_areas, psicologo.area_outra = _converter(psicologo.outras_areas, codigo_da_area)
        psicologo.save(update_fields=["abordagens", "abordagem_outra", "outras_areas", "area_outra"])


def _desconverter(codigos, escrito, rotulos):
    nomes = [rotulos[c] for c in codigos or [] if c in rotulos and c != OUTRA]
    if escrito:
        nomes.append(escrito)
    return nomes


def para_tras(apps, schema_editor):
    Psicologo = apps.get_model("contas", "Psicologo")
    for psicologo in Psicologo.objects.all().iterator():
        psicologo.abordagens = _desconverter(psicologo.abordagens, psicologo.abordagem_outra, ROTULO_DA_ABORDAGEM)
        psicologo.outras_areas = _desconverter(psicologo.outras_areas, psicologo.area_outra, ROTULO_DA_AREA)
        psicologo.save(update_fields=["abordagens", "outras_areas"])


class Migration(migrations.Migration):

    dependencies = [("contas", "0011_rls_mudanca_de_regime")]

    operations = [
        migrations.AddField(
            model_name="psicologo",
            name="abordagem_outra",
            field=models.CharField(blank=True, max_length=120, verbose_name="Qual abordagem"),
        ),
        migrations.AddField(
            model_name="psicologo",
            name="area_outra",
            field=models.CharField(blank=True, max_length=120, verbose_name="Qual área"),
        ),
        migrations.RunPython(para_frente, para_tras),
    ]

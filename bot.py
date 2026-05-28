import os
import re
import csv
import cv2
import numpy as np
import pytesseract

from dotenv import load_dotenv
from pyzbar.pyzbar import decode as pyzbar_decode

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, FSInputFile

# =========================================
# ENV
# =========================================

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

# =========================================
# TESSERACT
# =========================================

if os.name == "nt":
    pytesseract.pytesseract.tesseract_cmd = (
        r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    )

# =========================================
# BOT
# =========================================

bot = Bot(token=TOKEN)
dp = Dispatcher()
CSV_FILE = "nfce.csv"

# =========================================
# START
# =========================================

@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "✅ Bot NFC-e ativo.\n\n"
        "📎 Envie as notas como DOCUMENTO (arquivo)\n"
        "Isso melhora MUITO a leitura do QR Code."
    )

# =========================================
# COMANDO CSV
# =========================================

@dp.message(Command("csv"))
async def enviar_csv(message: Message):
    if not os.path.exists(CSV_FILE):
        await message.answer("Nenhum CSV encontrado.")
        return

    arquivo = FSInputFile(CSV_FILE)
    await message.answer_document(
        arquivo,
        caption="📄 CSV acumulado das NFC-e"
    )

# =========================================
# EXTRAIR CHAVE DO QR CODE
# =========================================

def extrair_chave_qr(qr_texto):
    # Formato da URL do PR: ...consulta?p=CHAVE44DIGITOS...
    match = re.search(r"p=(\d{44})", qr_texto)
    if match:
        return match.group(1)
    # Fallback: qualquer sequência de 44 dígitos no texto do QR
    match = re.search(r"\b(\d{44})\b", qr_texto)
    if match:
        return match.group(1)
    return ""

# =========================================
# LER QR CODE COM PYZBAR (MAIS ROBUSTO)
# =========================================

def tentar_ler_qr(img_bgr):
    """
    Tenta ler o QR Code com pyzbar em múltiplas
    variações da imagem. Retorna o texto ou "".
    """
    altura, largura = img_bgr.shape[:2]

    variacoes = []

    # 1. Imagem original em escala maior
    scale = max(1, 2000 // max(altura, largura))
    if scale > 1:
        grande = cv2.resize(
            img_bgr, None,
            fx=scale, fy=scale,
            interpolation=cv2.INTER_CUBIC
        )
    else:
        grande = img_bgr.copy()

    variacoes.append(grande)

    # 2. Grayscale
    gray = cv2.cvtColor(grande, cv2.COLOR_BGR2GRAY)
    variacoes.append(gray)

    # 3. Threshold adaptativo
    thresh = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 11, 2
    )
    variacoes.append(thresh)

    # 4. Sharpen
    kernel = np.array([[0, -1, 0],
                       [-1, 5, -1],
                       [0, -1, 0]])
    sharpened = cv2.filter2D(gray, -1, kernel)
    variacoes.append(sharpened)

    for variacao in variacoes:
        resultados = pyzbar_decode(variacao)
        for r in resultados:
            texto = r.data.decode("utf-8", errors="ignore")
            if texto:
                print(f"\n[QR pyzbar] {texto}\n")
                return texto

    return ""

# =========================================
# EXTRAIR CHAVE VIA OCR (FALLBACK)
# =========================================

def extrair_chave_ocr(texto):
    """
    Na nota fiscal impressa, a chave aparece no formato:
    '4126 0508 2278 7200 0280 6501 2000 0635 2610 1394 6932'
    (11 grupos de 4 dígitos = 44 dígitos)
    Vamos buscar esse padrão ANTES de tentar extrair
    sequência bruta — muito mais confiável.
    """

    # Padrão: 11 grupos de 4 dígitos separados por espaço
    padrao_grupos = re.compile(
        r'(\d{4}[\s\-]+\d{4}[\s\-]+\d{4}[\s\-]+'
        r'\d{4}[\s\-]+\d{4}[\s\-]+\d{4}[\s\-]+'
        r'\d{4}[\s\-]+\d{4}[\s\-]+\d{4}[\s\-]+'
        r'\d{4}[\s\-]+\d{4})'
    )

    match = padrao_grupos.search(texto)
    if match:
        chave = re.sub(r'\D', '', match.group(0))
        print(f"[OCR grupos] Chave: {chave}")
        if len(chave) == 44:
            return chave

    # Fallback: sequência contínua começando com 41
    # Faz substituições só nos dígitos, não no texto todo
    linhas = texto.split('\n')
    for linha in linhas:
        # Só processa linhas que parecem ser a linha da chave
        if re.search(r'\d[\s\d]{40,}\d', linha):
            nums = re.sub(r'\D', '', linha)
            match2 = re.search(r'41\d{42}', nums)
            if match2:
                print(f"[OCR fallback] Chave: {match2.group(0)}")
                return match2.group(0)

    return ""

# =========================================
# EXTRAIR DADOS DA CHAVE
# =========================================

def dados_da_chave(chave):
    dados = {
        "uf": "", "ano": "", "mes": "",
        "cnpj": "", "modelo": "",
        "serie": "", "documento": ""
    }

    if len(chave) != 44:
        return dados

    dados["uf"]        = chave[0:2]
    dados["ano"]       = chave[2:4]
    dados["mes"]       = chave[4:6]
    dados["cnpj"]      = chave[6:20]
    dados["modelo"]    = chave[20:22]
    dados["serie"]     = chave[22:25]
    dados["documento"] = chave[25:34].lstrip("0")

    return dados

# =========================================
# DUPLICIDADE
# =========================================

def chave_ja_existe(chave):
    if not os.path.exists(CSV_FILE):
        return False

    with open(CSV_FILE, "r", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter=";")
        for row in reader:
            if len(row) >= 11 and row[10] == chave:
                return True

    return False

# =========================================
# EXTRAIR VALOR
# =========================================

def extrair_valor(linhas, texto):
    valor = ""
    linhas_valor = []

    for i, linha in enumerate(linhas):
        l = linha.upper()
        if (
            "VALOR TOTAL" in l or
            "VALOR PAGO" in l or
            "DINHEIRO" in l or
            "PIX" in l
        ):
            linhas_valor.append(linha)
            for j in range(1, 3):
                if i + j < len(linhas):
                    linhas_valor.append(linhas[i + j])

    texto_valor = " ".join(linhas_valor)
    valores = re.findall(r"\d+[.,]\d{2}", texto_valor)

    candidatos = []
    for v in valores:
        try:
            num = float(v.replace(".", "").replace(",", "."))
            if 5 <= num <= 10000:
                candidatos.append((num, v))
        except:
            pass

    if candidatos:
        valor = max(candidatos)[1]

    if not valor:
        todos = re.findall(r"\d+[.,]\d{2}", texto)
        candidatos = []
        for v in todos:
            try:
                num = float(v.replace(".", "").replace(",", "."))
                if 5 <= num <= 10000:
                    candidatos.append((num, v))
            except:
                pass
        if candidatos:
            valor = max(candidatos)[1]

    return valor

# =========================================
# EXTRAIR PRODUTO
# =========================================

def extrair_produto(linhas):
    produtos_base = [
        "ETANOL", "GASOLINA", "DIESEL",
        "ARLA", "OLEO", "ÓLEO",
        "CAFE", "CAFÉ", "LEITE",
        "PÃO", "PAO", "LUBRIFICANTE"
    ]

    for linha in linhas:
        l = linha.upper()
        for p in produtos_base:
            if p in l:
                produto = linha.strip()
                produto = re.sub(r"^\d+\s*", "", produto)
                produto = re.sub(r"\s+", " ", produto)
                produto = produto.replace("? ", "")
                return produto

    return ""

# =========================================
# EXTRAIR DATA (MELHORADO)
# =========================================

def extrair_data(texto):
    # Busca a data da emissão, que aparece perto de "NFC-e" ou "Série"
    # Ex: "NFC-e nº000063526 Serie:12 23/05/2026 16:56:07"
    match = re.search(
        r'NFC.{0,20}?(\d{2}/\d{2}/\d{4})',
        texto,
        re.IGNORECASE
    )
    if match:
        return match.group(1)

    # Fallback: última data encontrada no texto
    datas = re.findall(r'\d{2}/\d{2}/\d{4}', texto)
    if datas:
        return datas[-1]

    return ""

# =========================================
# PROCESSAR ARQUIVO
# =========================================

async def processar_arquivo(
    message, file_id, file_path, extensao=".jpg"
):
    os.makedirs("imagens", exist_ok=True)
    caminho = f"imagens/{file_id}{extensao}"

    await bot.download_file(file_path, caminho)

    try:
        img = cv2.imread(caminho)

        if img is None:
            await message.answer("Erro ao abrir imagem.")
            return

        # =========================================
        # TENTAR QR CODE PRIMEIRO (pyzbar)
        # =========================================

        chave = ""
        qr_texto = tentar_ler_qr(img)

        if qr_texto:
            chave = extrair_chave_qr(qr_texto)

        # =========================================
        # OCR (sempre roda, para extrair outros dados)
        # =========================================

        # Pré-processamento para OCR de texto
        altura, largura = img.shape[:2]
        scale = max(1, 2000 // max(altura, largura))
        img_ocr = cv2.resize(
            img, None, fx=scale, fy=scale,
            interpolation=cv2.INTER_CUBIC
        )
        gray = cv2.cvtColor(img_ocr, cv2.COLOR_BGR2GRAY)
        gray = cv2.fastNlMeansDenoising(gray, h=10)
        _, gray = cv2.threshold(
            gray, 0, 255,
            cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )

        texto = pytesseract.image_to_string(
            gray, lang="por",
            config="--oem 3 --psm 6"
        )

        print("\n========== OCR ==========\n")
        print(texto)
        print("\n=========================\n")

        linhas = texto.split("\n")

        # =========================================
        # FALLBACK: CHAVE VIA OCR
        # =========================================

        if not chave or len(chave) != 44:
            chave = extrair_chave_ocr(texto)

        if len(chave) != 44:
            chave = ""

        # =========================================
        # SEM CHAVE
        # =========================================

        if not chave:
            await message.answer(
                "❌ Não consegui ler a chave NFC-e.\n\n"
                "📎 Tente enviar como DOCUMENTO.\n"
                "📸 Ou tire foto mais próxima do QR Code.\n\n"
                "💡 Dica: segure o celular paralelo à nota,\n"
                "sem inclinar, com boa iluminação."
            )
            return

        # =========================================
        # DUPLICIDADE
        # =========================================

        if chave_ja_existe(chave):
            await message.answer("⚠️ Essa NFC-e já foi adicionada.")
            return

        # =========================================
        # DADOS DA CHAVE
        # =========================================

        dados = dados_da_chave(chave)

        uf        = dados["uf"]
        ano       = dados["ano"]
        mes       = dados["mes"]
        cnpj      = dados["cnpj"]
        modelo    = dados["modelo"]
        serie     = dados["serie"]
        documento = dados["documento"]

        # CNPJ formatado para exibição
        cnpj_fmt = (
            f"{cnpj[0:2]}.{cnpj[2:5]}.{cnpj[5:8]}"
            f"/{cnpj[8:12]}-{cnpj[12:14]}"
            if len(cnpj) == 14 else cnpj
        )

        # =========================================
        # DATA, VALOR, PRODUTO
        # =========================================

        data    = extrair_data(texto)
        valor   = extrair_valor(linhas, texto)
        produto = extrair_produto(linhas)

        # =========================================
        # ESCREVER CSV
        # =========================================

        arquivo_existe = os.path.exists(CSV_FILE)

        with open(
            CSV_FILE, "a", newline="", encoding="utf-8"
        ) as f:
            writer = csv.writer(f, delimiter=";")

            if not arquivo_existe:
                writer.writerow([
                    "Data", "UF", "Ano", "Mes",
                    "CNPJ", "Modelo", "Serie",
                    "Documento", "Valor", "Produto", "Chave"
                ])

            writer.writerow([
                data, uf, ano, mes,
                cnpj, modelo, serie,
                documento, valor, produto, chave
            ])

        # =========================================
        # RESPOSTA
        # =========================================

        await message.answer(
            f"✅ NFC-e adicionada!\n\n"
            f"📅 Data: {data}\n"
            f"🏢 CNPJ: {cnpj_fmt}\n"
            f"🧾 Nº Documento: {documento}\n"
            f"📋 Série: {serie}\n"
            f"💰 Valor: R$ {valor}\n"
            f"🛒 Produto: {produto}\n"
            f"🔑 Chave: {chave}"
        )

    except Exception as e:
        print(e)
        await message.answer(f"Erro ao processar:\n{e}")

# =========================================
# FOTO
# =========================================

@dp.message(lambda message: message.photo)
async def receber_foto(message: Message):
    foto = message.photo[-1]
    arquivo = await bot.get_file(foto.file_id)
    await processar_arquivo(
        message, foto.file_id,
        arquivo.file_path, ".jpg"
    )

# =========================================
# DOCUMENTO
# =========================================

@dp.message(lambda message: message.document)
async def receber_documento(message: Message):
    documento = message.document
    nome = documento.file_name.lower()

    if not (
        nome.endswith(".jpg") or
        nome.endswith(".jpeg") or
        nome.endswith(".png")
    ):
        await message.answer("Envie apenas imagens.")
        return

    arquivo = await bot.get_file(documento.file_id)
    extensao = os.path.splitext(nome)[1]

    await processar_arquivo(
        message, documento.file_id,
        arquivo.file_path, extensao
    )

# =========================================
# START BOT
# =========================================

if __name__ == "__main__":
    print("✅ Bot rodando...")
    dp.run_polling(bot)
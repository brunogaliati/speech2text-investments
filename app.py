import os
from pytubefix import YouTube
from pytubefix.cli import on_progress
from deepgram import Deepgram
import asyncio
import json
from dotenv import load_dotenv
from openai import OpenAI
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.enums import TA_LEFT, TA_JUSTIFY
from reportlab.lib.fonts import addMapping
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Carregar variáveis de ambiente do arquivo .env
load_dotenv()

# Configuração do Deepgram
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
dg_client = Deepgram(DEEPGRAM_API_KEY)

# Configuração do OpenAI (usado apenas para o resumo)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# YouTube video URL
url = "https://www.youtube.com/watch?v=pgTBJ8olCGY&ab_channel=FinancialTimes"

# Initialize YouTube object with progress callback
yt = YouTube(url, on_progress_callback=on_progress)

# Print the video title
print(f"Video a ser processado: {yt.title}")

# Get audio-only stream
audio_stream = yt.streams.get_audio_only()

# Create the directory if it doesn't exist
os.makedirs('sample', exist_ok=True)

# Create a safe filename by removing invalid characters
safe_title = "".join(c for c in yt.title if c.isalnum() or c in (' ', '_')).rstrip()
# Usamos diretamente o formato webm para o Deepgram
webm_filename = os.path.join('sample', f"{safe_title}.webm")

# Verifica se o arquivo de áudio já existe
if not os.path.exists(webm_filename):
    print(f"Baixando áudio de: {yt.title}")
    # Baixa diretamente como webm (sem necessidade de converter)
    audio_stream.download(output_path='sample', filename=f"{safe_title}.webm")
else:
    print(f"Arquivo de áudio já existe: {webm_filename}. Pulando download.")

# Função para transcrever o áudio usando o Deepgram
async def transcribe_audio():
    print("Iniciando transcrição com Deepgram...")
    try:
        # Abrir o arquivo de áudio
        with open(webm_filename, 'rb') as audio:
            # Configurar fonte do áudio
            source = {'buffer': audio, 'mimetype': 'audio/webm'}
            
            # Realizar a transcrição usando o Deepgram
            response = await dg_client.transcription.prerecorded(
                source,
                {
                    'model': 'nova-3',  # Modelo mais recente da Deepgram
                    'smart_format': True,
                    'punctuate': True
                }
            )
            
            # Extrair o texto transcrito
            transcript = response['results']['channels'][0]['alternatives'][0]['transcript']
            return transcript
    except Exception as e:
        print(f"Erro na transcrição Deepgram: {e}")
        raise

def format_message(role, content):
    """Format a message for the OpenAI API."""
    return {"role": role, "content": content}

def get_response(messages):
    """Send a message to the OpenAI API and return the response."""
    completion = client.chat.completions.create(
        model='gpt-4o-mini',  # newest, cheapest model
        messages=messages,
    )
    return completion.choices[0].message.content

def create_wsj_style_pdf(output_path, title, summary):
    """Create a WSJ-style PDF with the summary."""
    # Try to use Georgia font (alternative to Escrow) for the title
    # and Source Sans Pro for the body text
    try:
        # Register fonts - if these fail, we'll fall back to default fonts
        try:
            pdfmetrics.registerFont(TTFont('Georgia', 'Georgia.ttf'))
            pdfmetrics.registerFont(TTFont('Georgia-Bold', 'Georgia Bold.ttf'))
            title_font = 'Georgia-Bold'
        except:
            title_font = 'Times-Bold'
        
        try:
            pdfmetrics.registerFont(TTFont('SourceSansPro', 'SourceSansPro-Regular.ttf'))
            body_font = 'SourceSansPro'
        except:
            body_font = 'Helvetica'
    except:
        title_font = 'Times-Bold'
        body_font = 'Helvetica'
    
    # Setup the document with proper margins (2.5cm = ~71 points)
    margin = 71
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin
    )
    
    # Create styles
    styles = getSampleStyleSheet()
    
    # Title style - WSJ style
    title_style = ParagraphStyle(
        'WSJ_Title',
        parent=styles['Title'],
        fontName=title_font,
        fontSize=26,
        leading=32,
        textColor=colors.black,
        alignment=TA_LEFT,
        spaceAfter=16
    )
    
    # Subtitle style for metadata
    subtitle_style = ParagraphStyle(
        'WSJ_Subtitle',
        parent=styles['Normal'],
        fontName=body_font,
        fontSize=10,
        leading=14,
        textColor=colors.gray,
        alignment=TA_LEFT,
        spaceBefore=0,
        spaceAfter=20
    )
    
    # Body text style - WSJ style - Now justified
    body_style = ParagraphStyle(
        'WSJ_Body',
        parent=styles['Normal'],
        fontName=body_font,
        fontSize=12,
        leading=21,  # 1.5 line spacing
        textColor=colors.gray,
        alignment=TA_JUSTIFY,  # Fully justified text
        spaceBefore=10
    )
    
    # Footer style for the source link
    footer_style = ParagraphStyle(
        'WSJ_Footer',
        parent=styles['Normal'],
        fontName=body_font,
        fontSize=9,
        leading=11,
        textColor=colors.gray,
        alignment=TA_LEFT,
        spaceBefore=30
    )
    
    # Create the PDF content
    story = []
    
    # Add the title
    story.append(Paragraph(title, title_style))
    
    # Add metadata (date, source, etc.)
    from datetime import datetime
    current_date = datetime.now().strftime("%B %d, %Y")
    metadata = f"Financial Times | {current_date} | Analysis by Bruno & ChatGPT"
    story.append(Paragraph(metadata, subtitle_style))
    
    # Add the summary with proper paragraphs
    paragraphs = summary.split('\n\n')
    for para in paragraphs:
        if para.strip():
            story.append(Paragraph(para, body_style))
            story.append(Spacer(1, 10))
    
    # Add source video link
    story.append(Spacer(1, 20))
    source_text = f"Source video: {url}"
    story.append(Paragraph(source_text, footer_style))
    
    # Build the PDF
    doc.build(story)
    print(f"PDF salvo em: {output_path}")

# Função principal que orquestra o fluxo
async def main():
    # Transcreve o áudio
    transcript = await transcribe_audio()
    
    # Define os caminhos dos arquivos de saída
    base_path = os.path.join('sample', f"{safe_title}")
    transcript_txt_path = f"{base_path}_transcription.txt"
    summary_txt_path = f"{base_path}_summary.txt"
    summary_pdf_path = f"{base_path}_summary.pdf"
    
    # Salva a transcrição em um arquivo de texto separado
    with open(transcript_txt_path, 'w', encoding='utf-8') as transcript_file:
        transcript_file.write(transcript)
    
    print(f"\nTranscrição salva em: {transcript_txt_path}")
    
    # Imprime a transcrição no console
    print("\nTranscrição: ")
    print(transcript)
    
    # Prepara as instruções para o resumo
    instructions = f"""
    You are an investment manager who uses several communication channels to convey information to clients regarding political and economic news, reports, and articles. 
    Please take the text below and create a summary for this purpose. 
    Use simple yet professional language. The idea is to summarize the central points of the text using different phrasing, always in the third person, referring to the person speaking in the text, not the manager themselves. 
    For example: I want to give an update based on a video I recently watched. The idea is that the recent changes...
    Avoid phrases like "the presenter said" or "the presenter concluded." Instead, use more direct expressions like: "The central idea is that the improvement..."
    Do not omit any points or arguments from the text. The goal is to summarize efficiently without losing content.
    Quotes: {transcript}
    """
    
    # Prepara a mensagem e obtém a resposta
    message = format_message("system", instructions)
    messages = [message]
    summary = get_response(messages)
    
    # Salva o resumo em um arquivo de texto separado
    with open(summary_txt_path, 'w', encoding='utf-8') as summary_file:
        summary_file.write(summary)
    
    print(f"\nResumo salvo em: {summary_txt_path}")
    
    # Prepara as instruções para a versão em inglês do resumo (para o PDF)
    english_instructions = f"""
    You are an investment manager who uses several communication channels to convey information to clients regarding political and economic news, reports, and articles. 
    Please take the text below and create a summary in English for this purpose.
    Use simple yet professional language. The idea is to summarize the central points of the text using different phrasing, always in the third person, referring to the person speaking in the text, not the manager themselves.
    For example: "The recent changes in monetary policy..."
    Avoid phrases like "the presenter said" or "the presenter concluded." Instead, use more direct expressions like: "The central idea is that the improvement..."
    Do not omit any points or arguments from the text. The goal is to summarize efficiently without losing content.
    Please make sure to structure the summary with proper paragraphs for better readability.
    Include specific details about Jamie Dimon's position as CEO of JPMorgan Chase, when this statement was made, and the context of the discussion if possible.
    Respond ONLY in English.
    Quotes: {transcript}
    """
    
    # Prepara a mensagem e obtém a resposta em inglês
    english_message = format_message("system", english_instructions)
    english_messages = [english_message]
    english_summary = get_response(english_messages)
    
    # Cria o PDF estilo WSJ com o resumo em inglês
    video_title = yt.title
    create_wsj_style_pdf(summary_pdf_path, video_title, english_summary)
    
    print(f"\nPDF com resumo em inglês salvo em: {summary_pdf_path}")

# Executa o programa principal
if __name__ == "__main__":
    asyncio.run(main())
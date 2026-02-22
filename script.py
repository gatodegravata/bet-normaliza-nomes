# @title Sistema de Sugestão Master - 6 Varreduras
import pandas as pd
from difflib import SequenceMatcher
import re
import json
import requests

# --- 1. CARREGAR REGRAS DE SUBSTITUIÇÃO (JSON DA URL) ---
try:
    response = requests.get(URL_SUBSTITUICOES)
    config_limpeza = response.json()
    print("✅ Regras de substituição carregadas via URL!")
except Exception as e:
    print(f"⚠️ Erro ao carregar JSON da URL: {e}. Usando dicionário vazio.")
    config_limpeza = {"termos_base": [], "substituicoes_times": {}}

def calcular_similaridade(a, b):
    return SequenceMatcher(None, str(a), str(b)).ratio()

def limpar_nome_futebol_pro(nome):
    nome = str(nome).upper()
    
    # 1. Padronização de Times de Base (carregado do JSON)
    for padrao, subst in config_limpeza['termos_base']:
        nome = re.sub(padrao, subst, nome)
    
    # 2. Dicionário de Substituições (carregado do JSON)
    for padrao, subst in config_limpeza['substituicoes_times'].items():
        nome = re.sub(padrao, subst, nome)
    
    # Remove anos específicos (ex: 1860, 1961)
    nome = re.sub(r'\b\d{4}\b', '', nome)
    
    return " ".join(nome.split())

print("🚀 Iniciando processamento para 1646 linhas...")

try:
    df_base_original = pd.read_parquet(URL_BASE)
    df_futuro_raw = pd.read_csv(URL_JOGOS_FUTUROS) 
    df_ligas = pd.read_csv(URL_LIGAS, sep=';')
    
    df_ligas['nome_errado'] = df_ligas['nome_errado'].str.strip().str.upper()
    df_ligas['nome_correto'] = df_ligas['nome_correto'].str.strip().str.upper()
    map_ligas = dict(zip(df_ligas['nome_errado'], df_ligas['nome_correto']))
    
    #df_master com os 1646 times únicos
    df_master = df_base_original[['League', 'Home']].copy()
    df_master['Home'] = df_master['Home'].str.strip().str.upper()
    df_master['League'] = df_master['League'].str.strip().str.upper().replace(map_ligas)
    df_master = df_master.drop_duplicates(subset=['Home'], keep='first')

    pool_hoje = df_futuro_raw[['League', 'Home']].copy()
    pool_hoje['Home'] = pool_hoje['Home'].str.strip().str.upper()
    pool_hoje['League'] = pool_hoje['League'].str.strip().str.upper()
    pool_hoje = pool_hoje.drop_duplicates()

    print("✅ Dados carregados!")
except Exception as e:
    print(f"❌ Erro: {e}")
    exit()

traducoes = {}

# --- V1 e V2: EXATOS ---
v1_match = pd.merge(df_master, pool_hoje, on=['League', 'Home'], how='inner').drop_duplicates(subset=['Home'])
for _, row in v1_match.iterrows():
    traducoes[row['Home']] = {'PARA_TIME': row['Home'], 'PARA_LEAGUE': row['League'], 'METODO': 'V1: EXATO TOTAL', 'SCORE': 1.0}

times_restantes = df_master[~df_master['Home'].isin(traducoes.keys())]
pool_restante = pool_hoje[~pool_hoje['Home'].isin([v['PARA_TIME'] for v in traducoes.values()])]

v2_match = pd.merge(times_restantes[['Home']], pool_restante, on='Home', how='inner').drop_duplicates(subset=['Home'])
for _, row in v2_match.iterrows():
    traducoes[row['Home']] = {'PARA_TIME': row['Home'], 'PARA_LEAGUE': row['League'], 'METODO': 'V2: NOME EXATO', 'SCORE': 1.0}

# --- V3: SIMILARIDADE (MESMA LIGA) ---
times_restantes = df_master[~df_master['Home'].isin(traducoes.keys())]
pool_restante = pool_hoje[~pool_hoje['Home'].isin([v['PARA_TIME'] for v in traducoes.values()])]

for _, row in times_restantes.iterrows():
    opcoes_na_liga = pool_restante[pool_restante['League'] == row['League']]
    melhor_s, match_f = 0, None
    for _, p_row in opcoes_na_liga.iterrows():
        s = 0.95 if (row['Home'] in p_row['Home'] or p_row['Home'] in row['Home']) else calcular_similaridade(row['Home'], p_row['Home'])
        if s > melhor_s and s > 0.7:
            melhor_s, match_f = s, p_row
    if match_f is not None:
        traducoes[row['Home']] = {'PARA_TIME': match_f['Home'], 'PARA_LEAGUE': match_f['League'], 'METODO': 'V3: SUBSTRING/LIGA', 'SCORE': round(melhor_s, 2)}
        pool_restante = pool_restante[pool_restante['Home'] != match_f['Home']]

# --- V4: LIGA APROXIMADA (RESTAURADA) ---
times_restantes = df_master[~df_master['Home'].isin(traducoes.keys())]
for _, row in times_restantes.iterrows():
    ligas_disponiveis = pool_restante['League'].unique()
    melhor_s_liga, liga_alvo = 0, ""
    for l_pool in ligas_disponiveis:
        s_l = calcular_similaridade(row['League'], l_pool)
        if s_l > melhor_s_liga and s_l > 0.7:
            melhor_s_liga, liga_alvo = s_l, l_pool
    if liga_alvo:
        opcoes_liga_prox = pool_restante[pool_restante['League'] == liga_alvo]
        melhor_s_t, match_t = 0, None
        for _, p_row in opcoes_liga_prox.iterrows():
            s_t = calcular_similaridade(row['Home'], p_row['Home'])
            if s_t > melhor_s_t and s_t > 0.7:
                melhor_s_t, match_t = s_t, p_row
        if match_t is not None:
            traducoes[row['Home']] = {'PARA_TIME': match_t['Home'], 'PARA_LEAGUE': match_t['League'], 'METODO': 'V4: LIGA APROXIMADA', 'SCORE': round(melhor_s_t, 2)}
            pool_restante = pool_restante[pool_restante['Home'] != match_t['Home']]

# --- V5: NORMALIZAÇÃO PRO ---
times_restantes = df_master[~df_master['Home'].isin(traducoes.keys())]
for _, row in times_restantes.iterrows():
    nome_base_limpo = limpar_nome_futebol_pro(row['Home'])
    for _, p_row in pool_restante.iterrows():
        nome_pool_limpo = limpar_nome_futebol_pro(p_row['Home'])
        if nome_base_limpo == nome_pool_limpo or nome_base_limpo in nome_pool_limpo or nome_pool_limpo in nome_base_limpo:
            traducoes[row['Home']] = {'PARA_TIME': p_row['Home'], 'PARA_LEAGUE': p_row['League'], 'METODO': 'V5: NORMALIZAÇÃO PRO', 'SCORE': 0.92}
            pool_restante = pool_restante[pool_restante['Home'] != p_row['Home']]
            break

# --- V6: IDENTIDADE POR CALENDÁRIO (JANEIRO 2025+) ---
print("🔍 Iniciando V6: Varredura por Calendário...")

# 1. Preparar as bases de datas
df_base_original['Date'] = pd.to_datetime(df_base_original['Date'])
df_futuro_raw['Date'] = pd.to_datetime(df_futuro_raw['Date'])

# Filtro a partir de Jan 2025
base_2025 = df_base_original[df_base_original['Date'] >= '2025-01-01']
futuro_2025 = df_futuro_raw[df_futuro_raw['Date'] >= '2025-01-01']

times_restantes = df_master[~df_master['Home'].isin(traducoes.keys())]

for _, row in times_restantes.iterrows():
    nome_time_base = row['Home']
    liga_base = row['League']
    
    # Datas que este time jogou na base (como Home ou Away - ideal conferir ambos se tiver a coluna)
    datas_time_base = set(base_2025[base_2025['Home'] == nome_time_base]['Date'])
    
    if len(datas_time_base) < 3: # Precisa de uma amostra mínima para ter confiança
        continue
        
    melhor_score_v6 = 0
    time_escolhido_v6 = None
    liga_escolhida_v6 = None

    # Candidatos no pool (apenas times que ainda não foram "casados")
    ja_casados = [v['PARA_TIME'] for v in traducoes.values()]
    candidatos_pool = futuro_2025[~futuro_2025['Home'].isin(ja_casados)]
    
    # Agrupamos por time no pool para ver quem tem mais datas em comum
    for nome_pool, group in candidatos_pool.groupby('Home'):
        datas_pool = set(group['Date'])
        
        # Interseção: datas em comum
        comuns = datas_time_base.intersection(datas_pool)
        score_v6 = len(comuns) / len(datas_time_base)
        
        if score_v6 >= 0.9 and score_v6 > melhor_score_v6:
            melhor_score_v6 = score_v6
            time_escolhido_v6 = nome_pool
            liga_escolhida_v6 = group['League'].iloc[0]

    if time_escolhido_v6:
        traducoes[nome_time_base] = {
            'PARA_TIME': time_escolhido_v6, 
            'PARA_LEAGUE': liga_escolhida_v6, 
            'METODO': 'V6: CALENDÁRIO (DNA)', 
            'SCORE': round(melhor_score_v6, 2)
        }

# --- FINALIZAÇÃO ---
df_final = df_master.copy()
df_final['SUGESTAO_TIME'] = df_final['Home'].map(lambda x: traducoes.get(x, {}).get('PARA_TIME', 'NÃO ENCONTRADO'))
df_final['SUGESTAO_LEAGUE'] = df_final['Home'].map(lambda x: traducoes.get(x, {}).get('PARA_LEAGUE', ''))
df_final['METODO'] = df_final['Home'].map(lambda x: traducoes.get(x, {}).get('METODO', 'FALHA'))
df_final['SCORE'] = df_final['Home'].map(lambda x: traducoes.get(x, {}).get('SCORE', 0))

# --- IMPRIMIR FALHAS NO TERMINAL ---
falhas = df_final[df_final['METODO'] == 'FALHA']

if not falhas.empty:
    print(f"\n⚠️  ATENÇÃO: {len(falhas)} TIMES NÃO ENCONTRADOS:")
    # Mostra a Liga e o Nome do time que falhou
    print(falhas[['League', 'Home']].to_string(index=False))
else:
    print("\n✅ SUCESSO TOTAL: Todos os times foram associados!")

# Depois disso vem o seu df_final.to_csv(...)

df_final.sort_values(by='SCORE', ascending=False).to_csv('sugestoes_finais_blindadas.csv', sep=';', index=False, decimal=',', encoding='utf-8-sig')

# --- GERAÇÃO DO ARQUIVO DE AJUSTES (MAPEAMENTO) ---

lista_ajustes = []

for nome_master, info in traducoes.items():
    # Pegamos o nome que foi sugerido (vinda do Pool/Jogos Futuros)
    nome_futuro = info['PARA_TIME']
    
    # Se o método não for FALHA e os nomes forem diferentes, a gente mapeia
    if info['METODO'] != 'FALHA' and nome_master != nome_futuro:
        lista_ajustes.append({
            'nome_errado': nome_master,  # O nome que está na sua base e você quer trocar
            'nome_correto': nome_futuro   # O nome "fresco" que veio dos jogos futuros
        })

# Criar o DataFrame
df_ajuste_nomes = pd.DataFrame(lista_ajustes)

# Salvar o CSV conforme seu comando
df_ajuste_nomes.to_csv('ajuste_nome_times.csv', 
                       sep=';', 
                       index=False, 
                       encoding='utf-8-sig')

print(f"✅ Arquivo 'ajuste_nome_times.csv' gerado!")
print(f"📍 Total de ajustes mapeados: {len(df_ajuste_nomes)}")

print(f"✨ Processo concluído! Associações: {len(df_final[df_final['METODO'] != 'FALHA'])} de {len(df_final)}")
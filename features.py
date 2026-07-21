import re
import pandas as pd
import numpy as np

STOP = set("""и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по
только ее мне было вот от меня еще нет о из ему теперь когда даже ну если уже или ни быть был
до вас нибудь вам ведь там потом себя может они тут где есть надо для мы их чем была раз тоже
под будет тогда кто этот того потому какой этого совсем этом один почти мой тем чтобы всех
можно при два другой после над больше тот через эти нас про них какая много эту моя перед
том такой всегда об услуг услуги услугу оказание право заключения договора нужд для дальнейшего
проведения работ работы выполнение""".split())

def stem6(word):
    return word[:6]

def clean_title(text):
    text = str(text).lower()
    words = re.findall(r'[а-яё]{3,}', text)
    words = [w for w in words if w not in STOP]
    stems = [stem6(w) for w in words]
    return ' '.join(stems)

def build_features(df):
    df = df.copy()
    df['название_стем'] = df['Название'].apply(clean_title)

    def group_method(x):
        xl = str(x).lower()
        if 'тендер' in xl or 'конкурс' in xl or 'аукцион' in xl:
            return 'Тендер/Конкурс'
        if 'запрос предложен' in xl:
            return 'Запрос предложений'
        if 'запрос цен' in xl or 'запрос котировок' in xl or 'запрос офер' in xl:
            return 'Запрос цен/котировок'
        if 'мониторинг' in xl:
            return 'Мониторинг цен'
        if 'предварительный отбор' in xl or 'попозицион' in xl:
            return 'Предварительный отбор'
        return 'Прочее'

    df['способ_группа'] = df['Способ отбора'].apply(group_method)
    df['москва'] = df['Регион'].astype(str).str.contains('Москва', na=False).astype(int)
    df['тип_торгов'] = df['Тип торгов'].fillna('Прочее')
    df['нмц_указана'] = df['НМЦ'].notna().astype(int)
    df['лог_цена'] = np.log1p(df['НМЦ'].fillna(0))

    pub = pd.to_datetime(df['Дата публикации'], errors='coerce')
    end = pd.to_datetime(df['Окончание приема заявок'], errors='coerce')
    df['дни_до_дедлайна'] = (end - pub).dt.total_seconds() / 86400
    df['дни_до_дедлайна'] = df['дни_до_дедлайна'].fillna(df['дни_до_дедлайна'].median())

    df['label'] = (df['Метка '].astype(str).str.strip() == 'Интересно').astype(int)
    df['дата_публикации'] = pub
    return df

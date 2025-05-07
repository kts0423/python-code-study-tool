from flask import Flask, render_template, request, session, redirect, url_for
import sys, io, os, re, json
from dotenv import load_dotenv
from openai import OpenAI

if getattr(sys, 'frozen', False):  # PyInstaller로 빌드된 실행파일일 경우
    base_path = sys._MEIPASS
else:
    base_path = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__, template_folder=os.path.join(base_path, 'templates'))
app.secret_key = 'your_secret_key'

# .env 경로를 실행 파일 기준으로 로드
env_path = os.path.join(os.path.dirname(sys.executable), '.env')
load_dotenv(env_path)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

users_file = os.path.join(os.path.dirname(sys.executable), 'users.json')
if os.path.exists(users_file):
    with open(users_file, 'r', encoding='utf-8') as f:
        users = json.load(f)
else:
    users = {}



@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name')
        student_id = request.form.get('student_id')

        if name and student_id.isdigit():
            if student_id in users:
                return render_template('register.html', error="이미 등록된 학번입니다.")
            users[student_id] = name
            with open(users_file, 'w', encoding='utf-8') as f:
                json.dump(users, f, ensure_ascii=False, indent=2)
            return redirect(url_for('login'))
        else:
            return render_template('register.html', error="이름과 숫자 학번을 정확히 입력해주세요.")

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        name = request.form.get('name')
        student_id = request.form.get('student_id')

        if name and student_id in users and users[student_id] == name:
            session['user'] = {"name": name, "student_id": student_id}
            session['history'] = []
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error="회원가입되지 않았거나 정보가 틀렸습니다.")

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/generate', methods=['POST'])
def generate():
    if 'user' not in session:
        return redirect(url_for('login'))

    category = request.form.get('category', 'for문')
    gpt_response = get_random_for_problem(category)
    parsed = parse_problem_response(gpt_response)

    global current_answer
    current_answer = parsed

    return render_template('index.html', problem=parsed['problem'], user=session['user'], category=category)

def get_random_for_problem(category="for문"):
    prompt = (
        f"Python의 {category}을 연습할 수 있는 초급 문제를 하나 만들어줘. "
        "아래 형식에 맞춰서 '문제', '정답 코드', '정답 출력값'을 각각 구분해서 명확하게 출력해줘. "
        "사용자 입력은 없이, 모든 값은 변수로 지정해서 문제를 구성해줘.\n\n"
        "예시 형식:\n"
        "### 문제:\n<문제 설명>\n\n"
        "### 정답 코드:\n<실행 가능한 파이썬 코드>\n\n"
        "### 정답 출력값:\n<실행 결과>"
    )
    response = client.chat.completions.create(
        model="gpt-4-turbo",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    return response.choices[0].message.content.strip()

def parse_problem_response(response_text):
    problem_match = re.search(r"### 문제:\n(.+?)### 정답 코드:", response_text, re.DOTALL)
    code_match = re.search(r"### 정답 코드:\n(.+?)### 정답 출력값:", response_text, re.DOTALL)
    output_match = re.search(r"### 정답 출력값:\n(.+)", response_text, re.DOTALL)

    return {
        "problem": problem_match.group(1).strip() if problem_match else "",
        "correct_code": code_match.group(1).strip() if code_match else "",
        "correct_output": output_match.group(1).strip() if output_match else "",
    }

def ask_gpt_is_logically_correct(problem, user_code, user_output, correct_code, correct_output):
    prompt = (
        f"### 문제 설명:\n{problem}\n\n"
        f"### GPT 정답 코드:\n{correct_code}\n\n"
        f"### GPT 예상 출력:\n{correct_output}\n\n"
        f"### 사용자 코드:\n{user_code}\n\n"
        f"### 사용자 출력 결과:\n{user_output}\n\n"
        "위 사용자의 코드가 GPT 정답 코드와는 다를 수 있지만, "
        "문제를 논리적으로 정확히 해결하고 있다면 '정답입니다' 라고 대답해주세요. "
        "틀렸다면 '오답입니다' 라고 명확히 답해주세요. 그 이유도 설명해줘."
    )

    response = client.chat.completions.create(
        model="gpt-4-turbo",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
    )
    return response.choices[0].message.content.strip()

@app.route('/')
def index():
    if 'user' not in session:
        return redirect(url_for('login'))

    return render_template('index.html', problem=None, user=session['user'])

@app.route('/submit', methods=['POST'])
def submit():
    if 'user' not in session:
        return redirect(url_for('login'))

    user_code = request.form['code']
    user_code = user_code.replace('\n', '\n')

    old_stdout = sys.stdout
    redirected_output = sys.stdout = io.StringIO()

    try:
        exec(user_code, {})
        user_result = redirected_output.getvalue().strip()
    except Exception as e:
        user_result = f"오류 발생: {e}"

    sys.stdout = old_stdout

    correct_output = current_answer.get("correct_output", "").strip()
    correct_code = current_answer.get("correct_code", "").strip()
    problem = current_answer.get("problem", "")

    gpt_judgement = ask_gpt_is_logically_correct(problem, user_code, user_result, correct_code, correct_output)
    is_correct = "정답" in gpt_judgement

    history = session.get('history', [])
    history.append({
        "problem": problem,
        "code": user_code,
        "output": user_result,
        "is_correct": is_correct
    })
    session['history'] = history

    return render_template(
        'result.html',
        result=user_result,
        is_correct=is_correct,
        correct_code=correct_code,
        correct_output=correct_output,
        problem=problem,
        code=user_code,
        gpt_judgement=gpt_judgement,
        history=history,
        user=session['user']
    )

if __name__ == '__main__':
    app.run(debug=True)

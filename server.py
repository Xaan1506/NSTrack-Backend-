from fastapi import FastAPI, APIRouter, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime, timezone, timedelta
from passlib.context import CryptContext
from jose import JWTError, jwt
# from emergentintegrations.llm.chat import LlmChat, UserMessage
import asyncio
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Security
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()
JWT_SECRET = os.environ.get('JWT_SECRET')
ALGORITHM = "HS256"

# Create the main app without a prefix
app = FastAPI()

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Pydantic Models
class UserSignup(BaseModel):
    name: str
    email: EmailStr
    password: str
    skill_level: str  # Beginner, Intermediate, Advanced
    batch: Optional[str] = None  # Turing, Hopper, Neumann, Ramanujan
    gender: Optional[str] = None  # Male, Female, Non-binary, etc.

class PasswordResetToken(BaseModel):
    email: EmailStr
    token: str
    type: str  # "reset" or "magic_link"
    expires_at: datetime

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

class MagicLoginRequest(BaseModel):
    token: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class User(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    email: str
    skill_level: str
    batch: Optional[str] = None
    gender: Optional[str] = None
    points: int = 10
    selected_track: Optional[str] = None
    following: List[str] = Field(default_factory=list)  # List of user IDs
    followers: List[str] = Field(default_factory=list)  # List of user IDs
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: User

class ProfileUpdate(BaseModel):
    points: Optional[int] = None
    selected_track: Optional[str] = None

class RoadmapRequest(BaseModel):
    track: str
    goals: str
    time_availability: str
    current_level: str

class Roadmap(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    track: str
    roadmap_data: Dict[str, Any]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ProblemRequest(BaseModel):
    track: str
    difficulty: str
    count: int = 5

class Problem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    track: str
    difficulty: str
    title: str
    description: str
    hints: List[str]
    solution_approach: str

class ProblemComplete(BaseModel):
    problem_id: str
    user_id: str

class LanguageContent(BaseModel):
    language: str
    section: str
    content: str

class FriendRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sender_id: str
    receiver_id: str
    status: str = "pending"  # pending, accepted, rejected
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class Friendship(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user1_id: str
    user2_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class FriendRequestAction(BaseModel):
    request_id: str

class Notification(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str  # Recipient of notification
    type: str  # "friend_request", "track_completed", "friend_accepted"
    title: str
    message: str
    link: Optional[str] = None  # URL to navigate to
    read: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

# Helper Functions
def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict, expires_delta: timedelta = timedelta(days=7)):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict:
    try:
        token = credentials.credentials
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid authentication credentials")
        
        user = await db.users.find_one({"id": user_id}, {"_id": 0})
        if user is None:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")

# Initialize LLM Chat
async def get_llm_chat(session_id: str, system_message: str):
    return LlmChat(
        api_key=os.environ.get('EMERGENT_LLM_KEY'),
        session_id=session_id,
        system_message=system_message
    ).with_model("anthropic", "claude-3-7-sonnet-20250219")

# Routes
@api_router.post("/auth/signup", response_model=TokenResponse)
async def signup(user_data: UserSignup):
    # Check if user exists
    existing_user = await db.users.find_one({"email": user_data.email})
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Set points based on skill level
    points_map = {"Beginner": 10, "Intermediate": 25, "Advanced": 50}
    points = points_map.get(user_data.skill_level, 10)
    
    # Create user
    user = User(
        name=user_data.name,
        email=user_data.email,
        skill_level=user_data.skill_level,
        batch=user_data.batch,
        gender=user_data.gender,
        points=points
    )
    
    user_dict = user.model_dump()
    user_dict['password_hash'] = hash_password(user_data.password)
    user_dict['created_at'] = user_dict['created_at'].isoformat()
    
    await db.users.insert_one(user_dict)
    
    # Create token
    access_token = create_access_token(data={"sub": user.id})
    
    return TokenResponse(access_token=access_token, user=user)

@api_router.post("/auth/login", response_model=TokenResponse)
async def login(credentials: UserLogin):
    user = await db.users.find_one({"email": credentials.email}, {"_id": 0})
    if not user or not verify_password(credentials.password, user['password_hash']):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    # Convert ISO string to datetime if needed
    if isinstance(user['created_at'], str):
        user['created_at'] = datetime.fromisoformat(user['created_at'])
    
    user_obj = User(**{k: v for k, v in user.items() if k != 'password_hash'})
    access_token = create_access_token(data={"sub": user_obj.id})
    
    return TokenResponse(access_token=access_token, user=user_obj)

@api_router.get("/auth/profile", response_model=User)
async def get_profile(current_user: Dict = Depends(get_current_user)):
    if isinstance(current_user['created_at'], str):
        current_user['created_at'] = datetime.fromisoformat(current_user['created_at'])
    return User(**{k: v for k, v in current_user.items() if k != 'password_hash'})

@api_router.put("/auth/profile", response_model=User)
async def update_profile(update_data: ProfileUpdate, current_user: Dict = Depends(get_current_user)):
    update_dict = {k: v for k, v in update_data.model_dump().items() if v is not None}
    
    if update_dict:
        await db.users.update_one(
            {"id": current_user['id']},
            {"$set": update_dict}
        )
    
    updated_user = await db.users.find_one({"id": current_user['id']}, {"_id": 0})
    if isinstance(updated_user['created_at'], str):
        updated_user['created_at'] = datetime.fromisoformat(updated_user['created_at'])
    
    return User(**{k: v for k, v in updated_user.items() if k != 'password_hash'})

@api_router.post("/roadmap/generate")
async def generate_roadmap(request: RoadmapRequest, current_user: Dict = Depends(get_current_user)):
    session_id = f"roadmap_{current_user['id']}_{request.track}"
    
    system_message = f"""You are an expert learning path advisor for NSTrack, a platform for NST college students.
Create personalized learning roadmaps that are:
- Structured in clear phases (Basics, Core, Advanced, Practice)
- Action-oriented with bullet points
- Include specific topics and milestones
- Practical and project-based

Student Context:
- Track: {request.track}
- Current Level: {request.current_level}
- Goals: {request.goals}
- Time Available: {request.time_availability}

Provide a comprehensive roadmap in this format:

## Phase 1: Foundations
- Topic 1: Description
- Topic 2: Description

## Phase 2: Core Skills
- Topic 1: Description
- Topic 2: Description

## Phase 3: Advanced Concepts
- Topic 1: Description
- Topic 2: Description

## Phase 4: Projects & Practice
- Project 1: Description
- Project 2: Description
"""
    
    chat = await get_llm_chat(session_id, system_message)
    user_message = UserMessage(text=f"Generate a complete roadmap for {request.track}")
    
    response = await chat.send_message(user_message)
    
    # Save roadmap
    roadmap = Roadmap(
        user_id=current_user['id'],
        track=request.track,
        roadmap_data={
            "content": response,
            "goals": request.goals,
            "time_availability": request.time_availability,
            "current_level": request.current_level
        }
    )
    
    roadmap_dict = roadmap.model_dump()
    roadmap_dict['created_at'] = roadmap_dict['created_at'].isoformat()
    
    await db.roadmaps.insert_one(roadmap_dict)
    
    return {"roadmap_id": roadmap.id, "content": response}

@api_router.get("/roadmap/{user_id}")
async def get_user_roadmaps(user_id: str, current_user: Dict = Depends(get_current_user)):
    if current_user['id'] != user_id:
        raise HTTPException(status_code=401, detail="Access denied")
    
    roadmaps = await db.roadmaps.find({"user_id": user_id}, {"_id": 0}).to_list(100)
    return roadmaps

@api_router.get("/languages/{lang}")
async def get_language_content(lang: str, section: Optional[str] = None):
    # Static structure with AI-enhanced examples
    language_structure = {
        "python": {
            "introduction": {"title": "Introduction to Python", "topics": ["Purpose", "Where Used", "Advantages"]},
            "setup": {"title": "Setup & First Program", "topics": ["Installation", "Hello World"]},
            "syntax": {"title": "Basic Syntax", "topics": ["Indentation", "Comments", "Variables"]},
            "datatypes": {"title": "Data Types", "topics": ["Numbers", "Strings", "Lists", "Tuples", "Dictionaries"]},
            "operators": {"title": "Operators", "topics": ["Arithmetic", "Comparison", "Logical", "Assignment"]},
            "conditionals": {"title": "Conditionals", "topics": ["if", "elif", "else"]},
            "loops": {"title": "Loops", "topics": ["for loop", "while loop", "break/continue"]},
            "functions": {"title": "Functions", "topics": ["Definition", "Parameters", "Return", "Lambda"]},
            "datastructures": {"title": "Data Structures", "topics": ["Lists", "Tuples", "Sets", "Dictionaries"]},
            "oop": {"title": "Object-Oriented Programming", "topics": ["Classes", "Objects", "Inheritance", "Polymorphism"]},
            "modules": {"title": "Libraries & Modules", "topics": ["Import", "Built-in Modules", "pip"]},
            "advanced": {"title": "Advanced Concepts", "topics": ["Decorators", "Generators", "Exception Handling"]},
            "projects": {"title": "Real-World Projects", "topics": ["Calculator", "To-Do List", "Web Scraper", "API Client", "Data Analyzer"]},
            "practice": {"title": "Practice Questions", "topics": ["Easy", "Medium", "Hard"]}
        },
        "java": {
            "introduction": {"title": "Introduction to Java", "topics": ["Purpose", "Where Used", "Advantages"]},
            "setup": {"title": "Setup & First Program", "topics": ["JDK Installation", "Hello World"]},
            "syntax": {"title": "Basic Syntax", "topics": ["Classes", "Methods", "Variables"]},
            "datatypes": {"title": "Data Types", "topics": ["Primitive Types", "Reference Types", "Arrays"]},
            "operators": {"title": "Operators", "topics": ["Arithmetic", "Comparison", "Logical", "Bitwise"]},
            "conditionals": {"title": "Conditionals", "topics": ["if-else", "switch", "ternary"]},
            "loops": {"title": "Loops", "topics": ["for", "while", "do-while", "enhanced for"]},
            "functions": {"title": "Methods", "topics": ["Declaration", "Parameters", "Return Types", "Overloading"]},
            "datastructures": {"title": "Data Structures", "topics": ["ArrayList", "HashMap", "LinkedList", "Stack", "Queue"]},
            "oop": {"title": "Object-Oriented Programming", "topics": ["Classes", "Objects", "Inheritance", "Polymorphism", "Encapsulation", "Abstraction"]},
            "modules": {"title": "Packages & Libraries", "topics": ["Import", "java.util", "java.io", "java.lang"]},
            "advanced": {"title": "Advanced Concepts", "topics": ["Interfaces", "Abstract Classes", "Exception Handling", "Threads"]},
            "projects": {"title": "Real-World Projects", "topics": ["Banking System", "Library Management", "Chat Application", "E-commerce Backend"]},
            "practice": {"title": "Practice Questions", "topics": ["Easy", "Medium", "Hard"]}
        },
        "cpp": {
            "introduction": {"title": "Introduction to C++", "topics": ["Purpose", "Where Used", "Advantages"]},
            "setup": {"title": "Setup & First Program", "topics": ["Compiler Setup", "Hello World"]},
            "syntax": {"title": "Basic Syntax", "topics": ["Structure", "Namespaces", "Comments"]},
            "datatypes": {"title": "Data Types", "topics": ["int", "float", "char", "bool", "string", "arrays"]},
            "operators": {"title": "Operators", "topics": ["Arithmetic", "Comparison", "Logical", "Bitwise"]},
            "conditionals": {"title": "Conditionals", "topics": ["if-else", "switch"]},
            "loops": {"title": "Loops", "topics": ["for", "while", "do-while"]},
            "functions": {"title": "Functions", "topics": ["Declaration", "Parameters", "Return", "Function Overloading"]},
            "datastructures": {"title": "Data Structures", "topics": ["Arrays", "Vectors", "Maps", "Sets", "Stacks", "Queues"]},
            "oop": {"title": "Object-Oriented Programming", "topics": ["Classes", "Objects", "Inheritance", "Polymorphism", "Encapsulation"]},
            "modules": {"title": "STL & Libraries", "topics": ["iostream", "vector", "algorithm", "string"]},
            "advanced": {"title": "Advanced Concepts", "topics": ["Pointers", "References", "Memory Management", "Templates"]},
            "projects": {"title": "Real-World Projects", "topics": ["Game Engine", "File Compressor", "Network Chat", "Database System"]},
            "practice": {"title": "Practice Questions", "topics": ["Easy", "Medium", "Hard"]}
        },
        "javascript": {
            "introduction": {"title": "Introduction to JavaScript", "topics": ["Purpose", "Where Used", "Advantages"]},
            "setup": {"title": "Setup & First Program", "topics": ["Browser Console", "Node.js", "Hello World"]},
            "syntax": {"title": "Basic Syntax", "topics": ["Statements", "Comments", "Variables"]},
            "datatypes": {"title": "Data Types", "topics": ["String", "Number", "Boolean", "Array", "Object"]},
            "operators": {"title": "Operators", "topics": ["Arithmetic", "Comparison", "Logical", "Ternary"]},
            "conditionals": {"title": "Conditionals", "topics": ["if-else", "switch"]},
            "loops": {"title": "Loops", "topics": ["for", "while", "forEach", "map"]},
            "functions": {"title": "Functions", "topics": ["Declaration", "Arrow Functions", "Callbacks", "Async/Await"]},
            "datastructures": {"title": "Data Structures", "topics": ["Arrays", "Objects", "Maps", "Sets"]},
            "oop": {"title": "Object-Oriented Programming", "topics": ["Classes", "Objects", "Inheritance", "Prototypes"]},
            "modules": {"title": "Modules & Libraries", "topics": ["Import/Export", "npm", "Popular Libraries"]},
            "advanced": {"title": "Advanced Concepts", "topics": ["Closures", "Promises", "Event Loop", "DOM Manipulation"]},
            "projects": {"title": "Real-World Projects", "topics": ["Todo App", "Weather App", "Chat App", "E-commerce Frontend"]},
            "practice": {"title": "Practice Questions", "topics": ["Easy", "Medium", "Hard"]}
        }
    }
    
    if lang.lower() not in language_structure:
        raise HTTPException(status_code=404, detail="Language not found")
    
    return {"language": lang, "structure": language_structure[lang.lower()]}

@api_router.post("/problems/generate")
async def generate_problems(request: ProblemRequest, current_user: Dict = Depends(get_current_user)):
    session_id = f"problems_{request.track}_{request.difficulty}"
    
    system_message = f"""You are a coding problem generator for NSTrack platform.
Generate {request.count} {request.difficulty} level problems for {request.track}.

**SPECIAL INSTRUCTIONS FOR HTML/CSS PROBLEMS:**
When generating HTML/CSS problems, include these requirements in the description:

1. **Structure the page using proper HTML elements**
   - Recreate every visible section shown in the reference
   - Use correct tags for inputs, labels, buttons, headings, containers, etc.
   - Maintain the same order and grouping as shown

2. **Style the page using CSS**
   Match the UI exactly by applying:
   - proper layout (flexbox/grid)
   - spacing (margin, padding)
   - fonts (size, weight)
   - colors (background, text, borders)
   - element sizes (inputs, buttons, boxes)
   - alignment (center, left, right)
   - borders and shadows (if visible)

3. **Responsiveness**
   - Include media queries to adjust layout on smaller screens
   - Ensure mobile-friendly behavior

4. **Output Requirements**
   Your final output should visually match the reference image in:
   - layout
   - spacing
   - sizing
   - color
   - alignment
   - typography

For each problem, provide:
1. Title (concise, descriptive)
2. Description (clear problem statement with reference image description)
3. 2-3 Hints (progressive difficulty)
4. Solution Approach (high-level algorithm)

Format each problem as:
---
TITLE: [Problem title]
DESCRIPTION: [Problem description]
HINTS: [hint1] | [hint2] | [hint3]
SOLUTION: [solution approach]
---
"""
    
    chat = await get_llm_chat(session_id, system_message)
    user_message = UserMessage(text=f"Generate {request.count} problems")
    
    response = await chat.send_message(user_message)
    
    # Parse response into problem objects
    problems = []
    problem_blocks = response.split('---')
    
    for block in problem_blocks:
        if 'TITLE:' in block:
            lines = block.strip().split('\n')
            title = ""
            description = ""
            hints = []
            solution = ""
            
            for line in lines:
                if line.startswith('TITLE:'):
                    title = line.replace('TITLE:', '').strip()
                elif line.startswith('DESCRIPTION:'):
                    description = line.replace('DESCRIPTION:', '').strip()
                elif line.startswith('HINTS:'):
                    hints_str = line.replace('HINTS:', '').strip()
                    hints = [h.strip() for h in hints_str.split('|')]
                elif line.startswith('SOLUTION:'):
                    solution = line.replace('SOLUTION:', '').strip()
            
            if title:
                problem = Problem(
                    track=request.track,
                    difficulty=request.difficulty,
                    title=title,
                    description=description,
                    hints=hints if hints else ["Think about the problem step by step"],
                    solution_approach=solution if solution else "Break down the problem into smaller parts"
                )
                problems.append(problem.model_dump())
    
    return {"problems": problems}

@api_router.post("/problems/complete")
async def complete_problem(data: ProblemComplete, current_user: Dict = Depends(get_current_user)):
    if current_user['id'] != data.user_id:
        raise HTTPException(status_code=401, detail="Access denied")
    
    # Record completion
    completion_record = {
        "id": str(uuid.uuid4()),
        "user_id": data.user_id,
        "problem_id": data.problem_id,
        "completed_at": datetime.now(timezone.utc).isoformat()
    }
    
    await db.problem_completions.insert_one(completion_record)
    
    return {"message": "Problem marked as complete"}

# Friend Request System
async def check_if_friends(user1_id: str, user2_id: str) -> bool:
    """Check if two users are friends"""
    friendship = await db.friendships.find_one({
        "$or": [
            {"user1_id": user1_id, "user2_id": user2_id},
            {"user1_id": user2_id, "user2_id": user1_id}
        ]
    })
    return friendship is not None

@api_router.post("/friends/request/{receiver_id}")
async def send_friend_request(receiver_id: str, current_user: Dict = Depends(get_current_user)):
    """Send a friend request to another user"""
    if current_user['id'] == receiver_id:
        raise HTTPException(status_code=400, detail="Cannot send friend request to yourself")
    
    # Check if receiver exists
    receiver = await db.users.find_one({"id": receiver_id})
    if not receiver:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Check if already friends
    if await check_if_friends(current_user['id'], receiver_id):
        raise HTTPException(status_code=400, detail="Already friends with this user")
    
    # Check if request already exists (pending)
    existing_request = await db.friend_requests.find_one({
        "$or": [
            {"sender_id": current_user['id'], "receiver_id": receiver_id, "status": "pending"},
            {"sender_id": receiver_id, "receiver_id": current_user['id'], "status": "pending"}
        ]
    })
    
    if existing_request:
        raise HTTPException(status_code=400, detail="Friend request already pending")
    
    # Create friend request
    friend_request = FriendRequest(
        sender_id=current_user['id'],
        receiver_id=receiver_id
    )
    
    request_dict = friend_request.model_dump()
    request_dict['created_at'] = request_dict['created_at'].isoformat()
    request_dict['updated_at'] = request_dict['updated_at'].isoformat()
    
    await db.friend_requests.insert_one(request_dict)
    
    # Create notification for receiver
    notification = Notification(
        user_id=receiver_id,
        type="friend_request",
        title="New Friend Request",
        message=f"{current_user['name']} sent you a friend request",
        link="/friends?tab=incoming"
    )
    await db.notifications.insert_one(notification.model_dump())
    
    return {"message": "Friend request sent successfully", "request_id": friend_request.id}

@api_router.get("/friends/requests/incoming")
async def get_incoming_requests(current_user: Dict = Depends(get_current_user)):
    """Get all incoming friend requests"""
    requests = await db.friend_requests.find(
        {"receiver_id": current_user['id'], "status": "pending"},
        {"_id": 0}
    ).to_list(1000)
    
    # Get sender details for each request
    for request in requests:
        sender = await db.users.find_one(
            {"id": request['sender_id']},
            {"_id": 0, "password_hash": 0}
        )
        if sender:
            request['sender'] = {
                "id": sender['id'],
                "name": sender['name'],
                "batch": sender.get('batch'),
                "skill_level": sender.get('skill_level')
            }
        if isinstance(request.get('created_at'), str):
            request['created_at'] = datetime.fromisoformat(request['created_at'])
    
    return {"requests": requests}

@api_router.get("/friends/requests/outgoing")
async def get_outgoing_requests(current_user: Dict = Depends(get_current_user)):
    """Get all outgoing friend requests"""
    requests = await db.friend_requests.find(
        {"sender_id": current_user['id'], "status": "pending"},
        {"_id": 0}
    ).to_list(1000)
    
    # Get receiver details for each request
    for request in requests:
        receiver = await db.users.find_one(
            {"id": request['receiver_id']},
            {"_id": 0, "password_hash": 0}
        )
        if receiver:
            request['receiver'] = {
                "id": receiver['id'],
                "name": receiver['name'],
                "batch": receiver.get('batch'),
                "skill_level": receiver.get('skill_level')
            }
        if isinstance(request.get('created_at'), str):
            request['created_at'] = datetime.fromisoformat(request['created_at'])
    
    return {"requests": requests}

@api_router.post("/friends/accept/{request_id}")
async def accept_friend_request(request_id: str, current_user: Dict = Depends(get_current_user)):
    """Accept a friend request"""
    # Get the request
    request = await db.friend_requests.find_one({"id": request_id}, {"_id": 0})
    
    if not request:
        raise HTTPException(status_code=404, detail="Friend request not found")
    
    if request['receiver_id'] != current_user['id']:
        raise HTTPException(status_code=403, detail="You can only accept requests sent to you")
    
    if request['status'] != "pending":
        raise HTTPException(status_code=400, detail="Request is not pending")
    
    # Update request status
    await db.friend_requests.update_one(
        {"id": request_id},
        {"$set": {"status": "accepted", "updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    
    # Create friendship
    friendship = Friendship(
        user1_id=request['sender_id'],
        user2_id=request['receiver_id']
    )
    
    friendship_dict = friendship.model_dump()
    friendship_dict['created_at'] = friendship_dict['created_at'].isoformat()
    
    await db.friendships.insert_one(friendship_dict)
    
    # Create notification for sender
    notification = Notification(
        user_id=request['sender_id'],
        type="friend_accepted",
        title="Friend Request Accepted",
        message=f"{current_user['name']} accepted your friend request",
        link="/friends"
    )
    await db.notifications.insert_one(notification.model_dump())
    
    return {"message": "Friend request accepted", "friendship_id": friendship.id}

@api_router.post("/friends/reject/{request_id}")
async def reject_friend_request(request_id: str, current_user: Dict = Depends(get_current_user)):
    """Reject a friend request"""
    # Get the request
    request = await db.friend_requests.find_one({"id": request_id}, {"_id": 0})
    
    if not request:
        raise HTTPException(status_code=404, detail="Friend request not found")
    
    if request['receiver_id'] != current_user['id']:
        raise HTTPException(status_code=403, detail="You can only reject requests sent to you")
    
    if request['status'] != "pending":
        raise HTTPException(status_code=400, detail="Request is not pending")
    
    # Update request status
    await db.friend_requests.update_one(
        {"id": request_id},
        {"$set": {"status": "rejected", "updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    
    return {"message": "Friend request rejected"}

@api_router.delete("/friends/remove/{friend_id}")
async def remove_friend(friend_id: str, current_user: Dict = Depends(get_current_user)):
    """Remove a friend"""
    # Remove friendship
    result = await db.friendships.delete_one({
        "$or": [
            {"user1_id": current_user['id'], "user2_id": friend_id},
            {"user1_id": friend_id, "user2_id": current_user['id']}
        ]
    })
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Friendship not found")
    
    return {"message": "Friend removed successfully"}

@api_router.get("/friends/list")
async def get_friends_list(current_user: Dict = Depends(get_current_user)):
    """Get list of all friends"""
    friendships = await db.friendships.find({
        "$or": [
            {"user1_id": current_user['id']},
            {"user2_id": current_user['id']}
        ]
    }, {"_id": 0}).to_list(1000)
    
    friend_ids = []
    for friendship in friendships:
        if friendship['user1_id'] == current_user['id']:
            friend_ids.append(friendship['user2_id'])
        else:
            friend_ids.append(friendship['user1_id'])
    
    # Get friend details with privacy - show full profile for friends
    friends = []
    if friend_ids:
        friends = await db.users.find(
            {"id": {"$in": friend_ids}},
            {"_id": 0, "password_hash": 0}
        ).to_list(1000)
        
        for friend in friends:
            if isinstance(friend.get('created_at'), str):
                friend['created_at'] = datetime.fromisoformat(friend['created_at'])
    
    return {"friends": friends}

@api_router.get("/friends/status/{user_id}")
async def check_friendship_status(user_id: str, current_user: Dict = Depends(get_current_user)):
    """Check friendship status with a user"""
    if current_user['id'] == user_id:
        return {"status": "self"}
    
    # Check if friends
    if await check_if_friends(current_user['id'], user_id):
        return {"status": "friends"}
    
    # Check for pending request sent by current user
    sent_request = await db.friend_requests.find_one({
        "sender_id": current_user['id'],
        "receiver_id": user_id,
        "status": "pending"
    })
    
    if sent_request:
        return {"status": "request_sent", "request_id": sent_request['id']}
    
    # Check for pending request received by current user
    received_request = await db.friend_requests.find_one({
        "sender_id": user_id,
        "receiver_id": current_user['id'],
        "status": "pending"
    })
    
    return {"status": "none"}


# User search endpoints
@api_router.get("/users")
async def get_users(batch: Optional[str] = None, current_user: Dict = Depends(get_current_user)):
    """Get all users with optional batch filter"""
    query = {}
    if batch and batch != "All":
        query["batch"] = batch
    
    users = await db.users.find(query, {"_id": 0, "password_hash": 0}).to_list(1000)
    
    # Convert created_at to datetime if needed
    for user in users:
        if isinstance(user.get('created_at'), str):
            user['created_at'] = datetime.fromisoformat(user['created_at'])
    
    return {"users": users}

@api_router.get("/search/users")
async def search_users(q: str, current_user: Dict = Depends(get_current_user)):
    """Search users by name"""
    users = await db.users.find(
        {"name": {"$regex": q, "$options": "i"}},
        {"_id": 0, "password_hash": 0}
    ).to_list(100)
    
    # Convert created_at to datetime if needed
    for user in users:
        if isinstance(user.get('created_at'), str):
            user['created_at'] = datetime.fromisoformat(user['created_at'])
    
    return {"users": users}


# Notification Endpoints
@api_router.get("/notifications/unread")
async def get_unread_notifications(current_user: Dict = Depends(get_current_user)):
    """Get all unread notifications"""
    notifications = await db.notifications.find(
        {"user_id": current_user['id'], "read": False},
        {"_id": 0}
    ).sort("created_at", -1).to_list(100)
    
    return {"notifications": notifications, "count": len(notifications)}

@api_router.get("/notifications")
async def get_notifications(current_user: Dict = Depends(get_current_user)):
    """Get all notifications"""
    notifications = await db.notifications.find(
        {"user_id": current_user['id']},
        {"_id": 0}
    ).sort("created_at", -1).to_list(50)
    
    return {"notifications": notifications}

@api_router.post("/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: str, current_user: Dict = Depends(get_current_user)):
    """Mark a notification as read"""
    result = await db.notifications.update_one(
        {"id": notification_id, "user_id": current_user['id']},
        {"$set": {"read": True}}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Notification not found")
    
    return {"message": "Notification marked as read"}

@api_router.post("/notifications/mark-all-read")
async def mark_all_notifications_read(current_user: Dict = Depends(get_current_user)):
    """Mark all notifications as read"""
    await db.notifications.update_many(
        {"user_id": current_user['id'], "read": False},
        {"$set": {"read": True}}
    )
    
    return {"message": "All notifications marked as read"}

@api_router.delete("/notifications/{notification_id}")
async def delete_notification(notification_id: str, current_user: Dict = Depends(get_current_user)):
    """Delete a notification"""
    result = await db.notifications.delete_one(
        {"id": notification_id, "user_id": current_user['id']}
    )
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Notification not found")
    
    return {"message": "Notification deleted"}

@api_router.post("/tracks/complete")
async def complete_track(track_data: dict, current_user: Dict = Depends(get_current_user)):
    """Complete a track and notify friends"""
    track_name = track_data.get('track')
    if not track_name:
        raise HTTPException(status_code=400, detail="Track name required")
        
    # Create notification for user
    user_notification = Notification(
        user_id=current_user['id'],
        type="track_completed",
        title="Track Completed! 🏆",
        message=f"Congratulations on completing the {track_name} track!",
        link="/profile"
    )
    await db.notifications.insert_one(user_notification.model_dump())
    
    # Notify friends
    friends_list = await get_friends_list(current_user)
    friends = friends_list.get('friends', [])
    
    for friend in friends:
        friend_notification = Notification(
            user_id=friend['id'],
            type="friend_track_completed",
            title="Friend Achievement",
            message=f"{current_user['name']} completed the {track_name} track!",
            link=f"/profile?user_id={current_user['id']}"
        )
        await db.notifications.insert_one(friend_notification.model_dump())
        
    return {"message": "Track completion recorded"}


    return {"message": "Track completion recorded"}


# Email Helper
def send_email(to_email: str, subject: str, body: str):
    """Send an email using Gmail SMTP"""
    sender_email = os.environ.get('MAIL_USERNAME')
    sender_password = os.environ.get('MAIL_PASSWORD')
    
    if not sender_email or not sender_password:
        print("WARNING: Email credentials not found. Printing to console instead.")
        print(f"To: {to_email}\nSubject: {subject}\nBody: {body}")
        return

    try:
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        # Connect to Gmail SMTP
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.send_message(msg)
            
        print(f"Email sent successfully to {to_email}")
    except Exception as e:
        print(f"Failed to send email: {str(e)}")
        # Fallback to console in case of error
        print(f"To: {to_email}\nSubject: {subject}\nBody: {body}")


# Password Recovery Endpoints
@api_router.post("/auth/forgot-password")
async def forgot_password(request: ForgotPasswordRequest):
    """Request a password reset or magic link"""
    # Case insensitive lookup
    email_lower = request.email.lower()
    
    # Try to find user with case-insensitive regex if exact match fails
    user = await db.users.find_one({"email": email_lower})
    if not user:
        # Try finding with case-insensitive regex
        user = await db.users.find_one({"email": {"$regex": f"^{email_lower}$", "$options": "i"}})
    
    if not user:
        # Don't reveal if user exists
        return {"message": "If an account exists, a recovery code has been sent."}
    
    # Use the email from the database to ensure consistency
    user_email = user['email']
    
    # Generate token
    token = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
    
    reset_token = PasswordResetToken(
        email=user_email,
        token=token,
        type="reset", # Can be used for both reset and magic link
        expires_at=expires_at
    )
    
    await db.password_resets.insert_one(reset_token.model_dump())
    
    # Send Email
    subject = "NSTrack Login Code"
    body = f"Your login/recovery code is: {token}\n\nThis code expires in 15 minutes."
    
    # Run in thread pool to not block async loop
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, send_email, user_email, subject, body)
    
    return {"message": "If an account exists, a recovery code has been sent."}

@api_router.post("/auth/reset-password")
async def reset_password(request: ResetPasswordRequest):
    """Reset password using token"""
    reset_token = await db.password_resets.find_one({
        "token": request.token,
        "expires_at": {"$gt": datetime.now(timezone.utc)}
    })
    
    if not reset_token:
        raise HTTPException(status_code=400, detail="Invalid or expired code")
        
    # Hash new password
    password_hash = hash_password(request.new_password)
    
    # Update user password
    await db.users.update_one(
        {"email": reset_token['email']},
        {"$set": {"password_hash": password_hash}}
    )
    
    # Delete used token
    await db.password_resets.delete_one({"token": request.token})
    
    return {"message": "Password successfully reset"}

@api_router.post("/auth/magic-login")
async def magic_login(request: MagicLoginRequest):
    """Login using magic link token"""
    reset_token = await db.password_resets.find_one({
        "token": request.token,
        "expires_at": {"$gt": datetime.now(timezone.utc)}
    })
    
    if not reset_token:
        raise HTTPException(status_code=400, detail="Invalid or expired code")
        
    # Get user
    user = await db.users.find_one({"email": reset_token['email']})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    # Create access token
    access_token = create_access_token(data={"sub": user['id']})
    
    # Delete used token
    await db.password_resets.delete_one({"token": request.token})
    
    # Convert _id to string for response
    user_response = User(**user)
    
    return TokenResponse(access_token=access_token, user=user_response)




# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
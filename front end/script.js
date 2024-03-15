// Mock data for topics (replace with actual data from your database)
let topicsData = [
    { id: 1, title: "Topic 1", author: "John Doe", date: "2024-03-15", content: "hi mates how's the weekend." },
    { id: 2, title: "Topic 2", author: "Jane Smith", date: "2024-03-14", content: "how is the spring break." },
    
];

// Function to display topics
function displayTopics(topics) {
    const topicsSection = document.getElementById('topics-section');
    topicsSection.innerHTML = ''; // Clear previous topics

    topics.forEach(topic => {
        const topicElement = document.createElement('div');
        topicElement.classList.add('topic');
        topicElement.innerHTML = `
            <h3>${topic.title}</h3>
            <p>By ${topic.author} on ${topic.date}</p>
            <p>${topic.content}</p>
            <button class="reply-btn" data-id="${topic.id}">Reply</button>
            <button class="delete-btn" data-id="${topic.id}">Delete</button>
        `;
        topicsSection.appendChild(topicElement);
    });
}

// Function to handle topic creation (for administrators)
function createTopic(title, author, content) {
    // Perform necessary actions to create a new topic (e.g., save to database)
    // For demonstration, let's add a new topic to the mock data
    const newTopic = {
        id: topicsData.length + 1,
        title: title,
        author: author,
        date: new Date().toISOString().slice(0, 10),
        content: content
    };
    topicsData.push(newTopic);
}

// Function to handle signup
function signUp(firstName, lastName, username, password) {
    // Perform necessary actions to sign up the user (e.g., save to database)
    // For demonstration, let's log the user details
    console.log("Signed up successfully!");
    console.log("First Name:", firstName);
    console.log("Last Name:", lastName);
    console.log("Username:", username);
    console.log("Password:", password);
    
    // Redirect to the forum page
    window.location.href = "forum.html"; // Redirect to the forum page
}

// Function to handle login
function login(username, password) {
    // Perform necessary actions to authenticate the user (e.g., validate credentials)
    // For demonstration, let's assume login is successful
    console.log("Login successful!");
    
    // Redirect to the forum page
    window.location.href = "forum.html"; // Redirect to the forum page
}

// Event listener for submitting the search form
document.getElementById('search-form').addEventListener('submit', function(event) {
    event.preventDefault(); // Prevent form submission
    const searchInput = document.getElementById('search-input').value.toLowerCase();
    const filteredTopics = topicsData.filter(topic => topic.title.toLowerCase().includes(searchInput));
    displayTopics(filteredTopics);
});

// Event listener for clicking the "Create New Topic" button
document.getElementById('create-topic-btn').addEventListener('click', function() {
    // For demonstration, let's prompt the user to enter topic details
    const title = prompt("Enter topic title:");
    const content = prompt("Enter topic content:");
    // Add functionality to get current user (for author)
    const author = "Admin"; // Replace with actual user information
    if (title && content) {
        createTopic(title, author, content);
        displayTopics(topicsData);
    }
});

// Event listener for submitting the login form
document.getElementById('login-form').addEventListener('submit', function(event) {
    event.preventDefault(); // Prevent form submission
    const username = document.getElementById('username').value;
    const password = document.getElementById('password').value;
    login(username, password);
});

// Event listener for submitting the signup form
document.getElementById('signup-form').addEventListener('submit', function(event) {
    event.preventDefault(); // Prevent form submission
    const firstName = document.getElementById('firstname').value;
    const lastName = document.getElementById('lastname').value;
    const username = document.getElementById('username').value;
    const password = document.getElementById('password').value;
    signUp(firstName, lastName, username, password);
});

// Initial display of topics
displayTopics(topicsData);

// Function to handle topic deletion (for administrators)
function deleteTopic(topicId) {
    // Perform necessary actions to delete the topic (e.g., remove from database)
    // For demonstration, let's remove the topic from the mock data
    topicsData = topicsData.filter(topic => topic.id !== topicId);
    displayTopics(topicsData);
}

// Event listener for clicking the "Delete" button on topics (visible to administrators)
document.getElementById('topics-section').addEventListener('click', function(event) {
    if (event.target.classList.contains('delete-btn')) {
        const topicId = parseInt(event.target.getAttribute('data-id'));
        deleteTopic(topicId);
    }
});

// Event listener for clicking the "Reply" button on topics
document.getElementById('topics-section').addEventListener('click', function(event) {
    if (event.target.classList.contains('reply-btn')) {
        const topicId = parseInt(event.target.getAttribute('data-id'));
        // Add functionality to handle reply action
        // For now, let's just log the topic id
        console.log("Reply to topic with ID:", topicId);
    }
});

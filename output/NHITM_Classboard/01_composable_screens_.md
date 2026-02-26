# Chapter 1: Composable Screens

Welcome to the NHITM Classboard tutorial! In this chapter, we're going to start building the foundation of our app's user interface (UI). Imagine you're building a house. Before you can connect rooms with hallways, you first need to build the individual rooms themselves, right?

That's exactly what **Composable Screens** are for in our Android app!

### What Problem Do Composable Screens Solve?

Our NHITM Classboard app will have different sections, like a "Home" page, an "About Us" page for the college, a "Faculty" list, and perhaps a "Gallery." If we tried to put all the code for *all* these different pages into one giant file, it would quickly become a messy and unmanageable nightmare!

Composable Screens solve this problem by letting us build each distinct visual part or "page" of our application separately. Each screen is like a self-contained room in our app's house, dedicated to a specific purpose and holding its own unique content.

### Understanding "Composable Screens"

Let's break down the term:

1.  **Composable**: In modern Android app development (using something called Jetpack Compose), a "Composable" is a special type of function. Think of it as a small, smart piece of code that knows how to draw something on your phone's screen. It could be a simple piece of text, an image, a button, or even an entire page!

2.  **Screens**: When we talk about "Screens" in this context, we mean a Composable function that represents an entire visual page or a major section of your app. For example, the entire "About Us" page you see on your phone is a single Composable Screen.

So, a **Composable Screen** is essentially a special function that builds and displays a complete page or significant section of your app's user interface.

### Creating Our First Composable Screen

Let's look at how a simple Composable Screen is made. All our Composable Screens for the Classboard app live in the `screens` package, which you can find at `app/src/main/java/com/example/nhitmclassboard/screens/`.

Here's an example from our project:

```kotlin
// File: app/src/main/java/com/example/nhitmclassboard/screens/AboutUs.kt
package com.example.nhitmclassboard.screens

import androidx.compose.material3.Text // We import Text to display text

import androidx.compose.runtime.Composable // This is crucial for Composable functions

@Composable // This tells Android that 'AboutUs' is a Composable function
fun AboutUs(){
    Text(text = "about us : Comps Vaale") // Displaying a simple text message
}
```

**What's happening here?**

*   `package com.example.nhitmclassboard.screens`: This line tells us where this file belongs in our project structure. All our individual screens are organized in this `screens` package.
*   `@Composable`: This is a special annotation. It's like a tag you put on a function to tell Android that this particular function is responsible for drawing UI elements on the screen. You *must* have this for any function that creates UI.
*   `fun AboutUs(){ ... }`: This is a regular Kotlin function, but because it has the `@Composable` annotation, it becomes a "Composable function." This specific function is named `AboutUs`, and its job is to represent our "About Us" screen.
*   `Text(text = "about us : Comps Vaale")`: Inside our `AboutUs` function, we're using another Composable function called `Text`. This `Text` function simply displays the given string on the screen. In a real app, this screen would contain much more detailed information about the "About Us" section!

### How Composable Screens Work (Behind the Scenes)

When you run the Classboard app and navigate to, say, the "About Us" section, here's what happens in a very simplified way:

1.  The app needs to show the "About Us" page.
2.  It looks for the `AboutUs()` Composable function.
3.  It calls this function.
4.  The `AboutUs()` function then executes its code, which in our simple example, means displaying the text "about us : Comps Vaale" on the screen.

It's like asking for a specific room in a house. When you ask for the "About Us" room, the app simply opens that specific room and shows you what's inside.

Here are a few more examples of Composable Screens from our project, illustrating how each one defines a different part of the app:

```kotlin
// File: app/src/main/java/com/example/nhitmclassboard/screens/Home.kt
package com.example.nhitmclassboard.screens

import androidx.compose.material3.Text
import androidx.compose.runtime.Composable

@Composable
fun Home(){
    Text(text = "home") // This is the content for our Home screen
}
```

```kotlin
// File: app/src/main/java/com/example/nhitmclassboard/screens/Faculty.kt
package com.example.nhitmclassboard.screens

import androidx.compose.material3.Text
import androidx.compose.runtime.Composable

@Composable
fun Faculty(){
    Text(text = "faculty...shreyas") // This is the content for our Faculty screen
}
```

As you can see, each of these files (`AboutUs.kt`, `Home.kt`, `Faculty.kt`, etc.) contains a single `@Composable` function that acts as a standalone screen. They are simple for now, but they can be built up to contain complex layouts, images, lists, and interactive elements.

### Summary

In this chapter, we learned that **Composable Screens** are the individual, self-contained building blocks of our app's user interface. They are special `@Composable` functions that define a distinct visual page or section of our application, much like separate rooms in a house. By organizing our UI into these independent screens, we keep our code clean, modular, and easy to manage.

Now that we know how to create individual rooms, the next logical step is to figure out how to move between these rooms! In the next chapter, we'll explore [App Navigation Routes](02_app_navigation_routes_.md), which are like the addresses for each of our screens, helping us navigate through the app.

---

Generated by [AI Codebase Knowledge Builder]
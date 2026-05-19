# Base Node image for the build stage
FROM node:20-alpine AS builder

# Set the working directory inside the container
WORKDIR /app

# Copy package files first to leverage Docker layer caching
COPY package*.json ./

# Install dependencies
RUN npm install

# Copy the rest of the application source code
COPY . .

# Build the Vite + React application
RUN npm run build

# Use a lightweight Nginx image to serve the built static files
FROM nginx:alpine

# Copy the build output from the builder stage to Nginx's html folder
COPY --from=builder /app/dist /usr/share/nginx/html

# Expose port 80 for the Nginx server
EXPOSE 80

# Run Nginx in the foreground
CMD ["nginx", "-g", "daemon off;"]

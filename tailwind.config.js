/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './app/templates/**/*.html',
  ],
  theme: {
    extend: {
      colors: {
        primary: { DEFAULT: '#00A651', dark: '#008f45', light: '#33b870' },
        secondary: { DEFAULT: '#015e54', dark: '#013d35' },
      },
      fontFamily: {
        sans: ['Montserrat', 'Public Sans', 'Helvetica Neue', 'Arial', 'sans-serif'],
      }
    }
  },
  plugins: [],
}

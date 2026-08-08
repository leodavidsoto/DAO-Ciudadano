# Frontend del piloto DAO Ciudadana

> Un build exitoso solo demuestra que el bundle compila. El producto sigue en
> modo piloto: identidad civil y membresía on-chain de producción están
> bloqueadas. Consulta [`../docs/AUDIT.md`](../docs/AUDIT.md) antes de desplegar.

## Desarrollo con Create React App

This project was bootstrapped with [Create React App](https://github.com/facebook/create-react-app).

## Available Scripts

In the project directory, you can run:

### `npm start`

Runs the app in the development mode.\
Open [http://localhost:3000](http://localhost:3000) to view it in your browser.

The page will reload when you make changes.\
You may also see any lint errors in the console.

### `npm test`

Launches the test runner in the interactive watch mode.\
See the section about [running tests](https://facebook.github.io/create-react-app/docs/running-tests) for more information.

### `npm run build`

Builds the app for production to the `build` folder.\
It correctly bundles React in production mode and optimizes the build for the best performance.

The build is minified and the filenames include the hashes.\
El bundle queda listo para validación en un entorno de preview; esto no equivale
a readiness funcional del sistema completo.

## Nota de seguridad de sesión

La sesión web de SIWE usa una cookie `HttpOnly`: el frontend no recibe, guarda
ni lee el JWT. Todas las solicitudes del cliente autenticado se envían con
credenciales y las mutaciones repiten en `X-CSRF-Token` el valor obtenido de
`POST /api/wallet/verify` o `GET /api/wallet/session`. Ese valor CSRF no autentica
por sí solo y se conserva únicamente en memoria.

El inicio de sesión solicita explícitamente `session_transport: "cookie"` y
confirma la cookie mediante `GET /api/wallet/session` antes de exponer una
sesión autenticada. `POST /api/wallet/logout` limpia la cookie en el backend y
el frontend limpia siempre su estado React. Al cargar una versión nueva también
se eliminan las claves heredadas `auth_token` y `auth_address` de
`localStorage`, sin tocar el secreto local de identidad ZK.

El transporte de mensajes MACI cifrados es una excepción deliberada: utiliza
un cliente separado sin cookies ni CSRF para no vincular una papeleta anónima
con la sesión SIWE. En producción, CORS debe permitir el origen exacto del
frontend con credenciales; un comodín `*` no es compatible con cookies seguras.

See the section about [deployment](https://facebook.github.io/create-react-app/docs/deployment) for more information.

### `npm run eject`

**Note: this is a one-way operation. Once you `eject`, you can't go back!**

If you aren't satisfied with the build tool and configuration choices, you can `eject` at any time. This command will remove the single build dependency from your project.

Instead, it will copy all the configuration files and the transitive dependencies (webpack, Babel, ESLint, etc) right into your project so you have full control over them. All of the commands except `eject` will still work, but they will point to the copied scripts so you can tweak them. At this point you're on your own.

You don't have to ever use `eject`. The curated feature set is suitable for small and middle deployments, and you shouldn't feel obligated to use this feature. However we understand that this tool wouldn't be useful if you couldn't customize it when you are ready for it.

## Learn More

You can learn more in the [Create React App documentation](https://facebook.github.io/create-react-app/docs/getting-started).

To learn React, check out the [React documentation](https://reactjs.org/).

### Code Splitting

This section has moved here: [https://facebook.github.io/create-react-app/docs/code-splitting](https://facebook.github.io/create-react-app/docs/code-splitting)

### Analyzing the Bundle Size

This section has moved here: [https://facebook.github.io/create-react-app/docs/analyzing-the-bundle-size](https://facebook.github.io/create-react-app/docs/analyzing-the-bundle-size)

### Making a Progressive Web App

This section has moved here: [https://facebook.github.io/create-react-app/docs/making-a-progressive-web-app](https://facebook.github.io/create-react-app/docs/making-a-progressive-web-app)

### Advanced Configuration

This section has moved here: [https://facebook.github.io/create-react-app/docs/advanced-configuration](https://facebook.github.io/create-react-app/docs/advanced-configuration)

### Deployment

This section has moved here: [https://facebook.github.io/create-react-app/docs/deployment](https://facebook.github.io/create-react-app/docs/deployment)

### `npm run build` fails to minify

This section has moved here: [https://facebook.github.io/create-react-app/docs/troubleshooting#npm-run-build-fails-to-minify](https://facebook.github.io/create-react-app/docs/troubleshooting#npm-run-build-fails-to-minify)
